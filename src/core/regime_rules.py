# -*- coding: utf-8 -*-
"""
===================================
市场策略蓝图 — 后处理规则引擎
===================================

职责：
1. 根据宏观 Regime (BULL/NEUTRAL/BEAR/CRISIS) 对 LLM 输出施加硬约束
2. 在 pipeline.process_single_stock() 中 LLM 分析结束后调用
3. 不修改 LLM 的推理过程，只覆盖最终输出的可操作字段

约束优先级（从高到低）：
  CRISIS → BEAR → CAUTION_MDD → NEUTRAL → BULL

字段覆盖：
  - operation_advice / llm_advice：降级映射
  - suggested_position_pct：仓位上限压制
  - stop_loss：收紧系数（乘法）

注意：此模块为纯规则逻辑，无数据库/API调用，可安全测试。
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ===========================
# 规则表（可配置）
# ===========================

REGIME_RULES: Dict[str, Dict[str, Any]] = {
    "BULL": {
        "max_pos_pct": 30,       # 仓位上限 %
        "stop_mult": 1.0,         # 止损系数（1.0=不变）
        "advice_downgrade": {},   # 建议降级映射（空=不降级）
        "label": "牛市",
    },
    "NEUTRAL": {
        "max_pos_pct": 20,
        "stop_mult": 1.0,
        "advice_downgrade": {},
        "label": "中性",
    },
    "BEAR": {
        "max_pos_pct": 10,
        "stop_mult": 0.75,        # 止损收紧至原始的75%
        "advice_downgrade": {},   # 不强制降级建议：回测显示高分买入仍有57.8%胜率
                                  # 只通过仓位上限(10%)和止损收紧来控制风险
        "label": "熊市",
    },
    "CRISIS": {
        "max_pos_pct": 0,
        "stop_mult": 0.5,
        "advice_downgrade": {
            "买入": "观望",
            "加仓": "观望",
            "持有": "观望",
            "等待": "观望",
        },
        "label": "危机",
    },
}

# MaxDD Guard 额外约束（在 Regime 约束之上叠加）
MDD_GUARD_RULES: Dict[str, Dict[str, Any]] = {
    "caution": {
        "max_pos_pct_multiplier": 0.5,   # 仓位上限再乘0.5
        "stop_mult_extra": 0.9,
        "advice_downgrade": {},
    },
    "defensive": {
        "max_pos_pct_multiplier": 0.3,
        "stop_mult_extra": 0.8,
        "advice_downgrade": {
            "买入": "观望",
            "加仓": "持有",
        },
    },
    "halt": {
        "max_pos_pct_multiplier": 0.0,
        "stop_mult_extra": 0.7,
        "advice_downgrade": {
            "买入": "观望",
            "加仓": "观望",
            "持有": "观望",
            "等待": "观望",
        },
    },
}


def _downgrade_advice(advice: Optional[str], mapping: Dict[str, str]) -> Optional[str]:
    """按降级映射表覆盖 advice；不在映射中的值原样返回。"""
    if not advice or not mapping:
        return advice
    return mapping.get(advice, advice)


def apply_regime_constraints(
    result: Any,
    macro_regime: Optional[Dict[str, Any]] = None,
    max_dd_guard: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    在 LLM 分析结果上施加宏观 Regime 硬约束。

    Args:
        result: AnalysisResult 对象（就地修改）
        macro_regime: pipeline 传入的宏观 Regime dict，含 'regime' 字段
        max_dd_guard: pipeline 传入的 MaxDD guard dict，含 'guard_level' 字段

    Returns:
        修改后的 result（同一对象）
    """
    if result is None:
        return result

    regime_key = (macro_regime or {}).get("regime", "").upper() if macro_regime else ""
    mdd_level = (max_dd_guard or {}).get("guard_level", "normal") if max_dd_guard else "normal"

    rule = REGIME_RULES.get(regime_key)
    mdd_rule = MDD_GUARD_RULES.get(mdd_level) if mdd_level != "normal" else None

    if not rule and not mdd_rule:
        return result

    applied: list = []

    # ── 1. operation_advice / llm_advice 降级 ──────────────────────────
    for field in ("operation_advice", "llm_advice"):
        orig = getattr(result, field, None)
        if orig is None:
            continue
        new_val = orig
        if rule:
            new_val = _downgrade_advice(new_val, rule["advice_downgrade"])
        if mdd_rule:
            new_val = _downgrade_advice(new_val, mdd_rule["advice_downgrade"])
        if new_val != orig:
            setattr(result, field, new_val)
            applied.append(f"{field}: {orig}→{new_val}")

    # ── 2. position_sizing（从 dashboard.battle_plan.position_sizing）──
    try:
        dashboard = getattr(result, "dashboard", None) or {}
        bp = dashboard.get("battle_plan") or {}
        ps = bp.get("position_sizing") or {}
        if isinstance(ps, dict) and ps.get("suggested_pct") not in (None, "LLM自行估算"):
            orig_pct = float(ps["suggested_pct"])

            # Regime 上限
            max_pct = rule["max_pos_pct"] if rule else 30
            # MaxDD 进一步压制
            if mdd_rule:
                max_pct = max_pct * mdd_rule["max_pos_pct_multiplier"]

            if orig_pct > max_pct:
                ps["suggested_pct"] = round(max_pct, 1)
                if "rationale" in ps:
                    label = (rule or {}).get("label", regime_key)
                    ps["rationale"] += f"（{label}约束→上限{max_pct}%）"
                applied.append(f"position_pct: {orig_pct}%→{max_pct}%")
    except Exception:
        pass

    # ── 3. stop_loss 收紧 ───────────────────────────────────────────────
    try:
        stop = getattr(result, "stop_loss", None)
        current_price = getattr(result, "current_price", None) or getattr(result, "price", None)
        if stop and current_price and float(stop) > 0 and float(current_price) > 0:
            mult = rule["stop_mult"] if rule else 1.0
            if mdd_rule:
                mult *= mdd_rule["stop_mult_extra"]
            if mult < 1.0:
                orig_stop = float(stop)
                cur = float(current_price)
                # 收紧：把止损线往当前价方向移动
                gap = cur - orig_stop
                new_stop = round(cur - gap * mult, 2)
                if new_stop > orig_stop:
                    result.stop_loss = new_stop
                    applied.append(f"stop_loss: {orig_stop:.2f}→{new_stop:.2f}(×{mult:.2f})")
    except Exception:
        pass

    if applied:
        label = (rule or {}).get("label", regime_key) or mdd_level
        logger.info(f"[RegimeRules] {label} 约束已应用: {', '.join(applied)}")

    return result

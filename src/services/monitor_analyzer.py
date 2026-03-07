# -*- coding: utf-8 -*-
"""
持仓监控专属 AI 诊断服务

与完整的 Flash+Pro 分析不同，本模块针对已持仓股票的监控触发场景，
使用精简的 Prompt 组合，快速给出"三选一"的操作决策建议。

触发场景：
- 止损触发（price <= atr_stop）
- 目标价触及（price >= take_profit）
- 加仓信号（intraday pullback_rally + pnl > 5%）
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

_MONITOR_DIAGNOSE_COOLDOWN_HOURS = 2  # 同类触发最短间隔（小时）
_MONITOR_DIAGNOSE_MAX_PER_DAY = 3      # 每股每日最多 AI 诊断次数


def _get_cached_analysis_context(code: str) -> Dict[str, Any]:
    """从最近一次全量分析记录中提取基本面/舆情摘要（供监控诊断上下文）。

    有效期：基本面 72h，舆情 24h。超期则标注"可能已过期"。
    """
    try:
        from src.storage import DatabaseManager, AnalysisHistory
        from sqlalchemy import select, desc
        db = DatabaseManager.get_instance()
        with db.get_session() as session:
            rec = session.execute(
                select(AnalysisHistory)
                .where(AnalysisHistory.code == code)
                .order_by(desc(AnalysisHistory.created_at))
                .limit(1)
            ).scalar_one_or_none()
        if not rec:
            return {}
        raw = json.loads(rec.raw_result) if rec.raw_result else {}
        hours_ago = (datetime.now() - rec.created_at).total_seconds() / 3600 if rec.created_at else 999

        dashboard = raw.get('dashboard', {})
        f10_summary = dashboard.get('f10_summary', '') or ''
        news_summary = dashboard.get('news_summary', '') or ''
        market_regime = dashboard.get('market_regime', '') or ''
        battle_plan = dashboard.get('battle_plan', {}) or {}
        holding_horizon_ai = battle_plan.get('holding_horizon', '')

        stale_note = f"（⚠️ 以下信息来自 {hours_ago:.0f} 小时前的分析，可能已过期）" if hours_ago > 24 else ""
        news_stale = "（⚠️ 舆情超过24小时，请自行确认是否有新消息）" if hours_ago > 24 else ""

        return {
            'hours_ago': hours_ago,
            'f10_summary': f10_summary,
            'news_summary': news_summary,
            'market_regime': market_regime,
            'holding_horizon_ai': holding_horizon_ai,
            'stale_note': stale_note,
            'news_stale': news_stale,
            'last_score': rec.sentiment_score,
            'last_advice': rec.operation_advice or '',
        }
    except Exception as e:
        logger.debug(f"[monitor_analyzer] 获取缓存分析上下文失败: {e}")
        return {}


def _check_diagnose_throttle(code: str, trigger_type: str) -> bool:
    """检查是否超过限流阈值（每日最多 N 次，同类型最小 2 小时间隔）。

    Returns True 表示允许执行诊断，False 表示被限流。
    """
    try:
        from src.storage import DatabaseManager
        from sqlalchemy import text
        db = DatabaseManager.get_instance()
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        with db.get_session() as session:
            # 今日诊断次数
            count_today = session.execute(text(
                "SELECT COUNT(*) FROM monitor_diagnoses WHERE code=:code AND created_at>=:today"
            ).bindparams(code=code, today=today_start)).scalar() or 0
            if count_today >= _MONITOR_DIAGNOSE_MAX_PER_DAY:
                logger.info(f"[monitor_analyzer] {code} 今日诊断已达上限({_MONITOR_DIAGNOSE_MAX_PER_DAY}次)")
                return False
            # 同类型最近触发时间
            cutoff = datetime.now() - timedelta(hours=_MONITOR_DIAGNOSE_COOLDOWN_HOURS)
            last = session.execute(text(
                "SELECT created_at FROM monitor_diagnoses WHERE code=:code AND trigger_type=:tt ORDER BY created_at DESC LIMIT 1"
            ).bindparams(code=code, tt=trigger_type)).fetchone()
            if last and last[0] and last[0] > cutoff:
                logger.info(f"[monitor_analyzer] {code} {trigger_type} 距上次诊断不足{_MONITOR_DIAGNOSE_COOLDOWN_HOURS}h，跳过")
                return False
        return True
    except Exception:
        return True  # 查询失败时允许执行


def _save_diagnose_result(
    code: str,
    trigger_type: str,
    decision: str,
    action_price: Optional[float],
    new_stop: Optional[float],
    next_checkpoint: str,
    reasoning: str,
) -> None:
    """将监控诊断结果写入 monitor_diagnoses 表（独立于 analysis_history）。"""
    try:
        from src.storage import DatabaseManager
        from sqlalchemy import text
        db = DatabaseManager.get_instance()
        with db.get_session() as session:
            session.execute(text("""
                INSERT INTO monitor_diagnoses
                    (code, trigger_type, decision, action_price, new_stop, next_checkpoint, reasoning, created_at)
                VALUES (:code, :tt, :dec, :ap, :ns, :nc, :r, :ts)
            """).bindparams(
                code=code, tt=trigger_type, dec=decision,
                ap=action_price, ns=new_stop, nc=next_checkpoint,
                r=reasoning, ts=datetime.now()
            ))
            session.commit()
    except Exception as e:
        logger.debug(f"[monitor_analyzer] 保存诊断结果失败: {e}")


def quick_diagnose(
    code: str,
    name: str,
    trigger_type: str,
    cost_price: float,
    current_price: float,
    atr_stop: float,
    pnl_pct: float,
    intraday_info: Dict[str, Any],
    holding_horizon_user: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    监控触发的 AI 快速诊断（精简版 Flash+Pro）。

    Returns:
        {'decision': 'A/B/C', 'action_price': X, 'new_stop': X,
         'next_checkpoint': '...', 'reasoning': '...'}
        或 None（限流/API失败）
    """
    if not _check_diagnose_throttle(code, trigger_type):
        return None

    cached_ctx = _get_cached_analysis_context(code)
    holding_days = 0
    try:
        from src.storage import DatabaseManager, Portfolio
        from sqlalchemy import select
        db = DatabaseManager.get_instance()
        with db.get_session() as session:
            p = session.execute(select(Portfolio).where(Portfolio.code == code)).scalar_one_or_none()
            if p and p.entry_date:
                holding_days = (datetime.now().date() - p.entry_date).days
    except Exception:
        pass

    holding_horizon_ai = cached_ctx.get('holding_horizon_ai', '')
    horizon_conflict = ''
    effective_horizon = holding_horizon_user or holding_horizon_ai or '未知'
    if holding_horizon_user and holding_horizon_ai and holding_horizon_user != holding_horizon_ai:
        horizon_conflict = (
            f"\n⚠️【持仓周期分歧】用户意图：{holding_horizon_user}，上次AI建议：{holding_horizon_ai}。"
            f"请基于较短周期（更保守）给出决策，并在reasoning中说明是否建议用户调整持仓周期预期。"
        )

    trigger_desc = {
        'stop_loss': f"ATR追踪止损线 {atr_stop:.2f} 被触及",
        'take_profit': f"目标价附近，浮盈 {pnl_pct:+.1f}%",
        'add_signal': f"回踩拉升信号，浮盈 {pnl_pct:+.1f}%",
    }.get(trigger_type, trigger_type)

    intraday_text = _format_intraday_for_monitor(intraday_info)
    market_regime = cached_ctx.get('market_regime', '')
    regime_hint = f"大盘形态：{market_regime}" if market_regime else ''
    news_stale = cached_ctx.get('news_stale', '')
    f10_brief = (cached_ctx.get('f10_summary') or '')[:200]
    news_brief = (cached_ctx.get('news_summary') or '')[:200]
    last_score = cached_ctx.get('last_score', '')
    last_advice = cached_ctx.get('last_advice', '')
    stale_note = cached_ctx.get('stale_note', '')
    hours_ago = cached_ctx.get('hours_ago', 999)

    flash_result = _run_monitor_flash(
        code=code, name=name, trigger_type=trigger_type, trigger_desc=trigger_desc,
        cost_price=cost_price, current_price=current_price, atr_stop=atr_stop,
        pnl_pct=pnl_pct, holding_days=holding_days, effective_horizon=effective_horizon,
        intraday_text=intraday_text, regime_hint=regime_hint,
    )

    pro_result = _run_monitor_pro(
        code=code, name=name, trigger_type=trigger_type, trigger_desc=trigger_desc,
        cost_price=cost_price, current_price=current_price, atr_stop=atr_stop,
        pnl_pct=pnl_pct, holding_days=holding_days, effective_horizon=effective_horizon,
        intraday_text=intraday_text, flash_result=flash_result,
        f10_brief=f10_brief, news_brief=news_brief, last_score=last_score,
        last_advice=last_advice, stale_note=stale_note, hours_ago=hours_ago,
        news_stale=news_stale, regime_hint=regime_hint, horizon_conflict=horizon_conflict,
    )

    if pro_result:
        _save_diagnose_result(
            code=code, trigger_type=trigger_type,
            decision=pro_result.get('decision', ''),
            action_price=pro_result.get('action_price'),
            new_stop=pro_result.get('new_stop'),
            next_checkpoint=pro_result.get('next_checkpoint', ''),
            reasoning=pro_result.get('reasoning', ''),
        )
        _push_diagnose_result(code=code, name=name, trigger_desc=trigger_desc, result=pro_result)

    return pro_result


def _format_intraday_for_monitor(intraday_info: Dict[str, Any]) -> str:
    """将分时信号格式化为简洁的文本描述供 Prompt 使用。"""
    if not intraday_info:
        return "（盘中数据不可用）"
    parts = []
    if intraday_info.get('intraday_trend'):
        parts.append(f"分时趋势：{intraday_info['intraday_trend']}")
    if intraday_info.get('vwap_position'):
        parts.append(f"VWAP位置：{intraday_info['vwap_position']}")
    if intraday_info.get('momentum'):
        parts.append(f"动能：{intraday_info['momentum']}")
    if intraday_info.get('volume_distribution'):
        parts.append(f"量能分布：{intraday_info['volume_distribution']}")
    if intraday_info.get('monitor_signal'):
        sig_map = {'distribute': '⚠️主力出货特征', 'pullback_rally': '✅尾盘拉升特征'}
        parts.append(f"综合信号：{sig_map.get(intraday_info['monitor_signal'], intraday_info['monitor_signal'])}")
    if intraday_info.get('summary'):
        parts.append(f"摘要：{intraday_info['summary']}")
    return ' | '.join(parts) if parts else "（盘中数据不完整）"


def _run_monitor_flash(
    code: str, name: str, trigger_type: str, trigger_desc: str,
    cost_price: float, current_price: float, atr_stop: float,
    pnl_pct: float, holding_days: int, effective_horizon: str,
    intraday_text: str, regime_hint: str,
) -> Optional[str]:
    """运行监控专属 Flash 诊断（持仓风险诊断师角色）。"""
    try:
        from src.config import Config
        from concurrent.futures import ThreadPoolExecutor
        cfg = Config()
        try:
            import google.generativeai as genai
            genai.configure(api_key=cfg.gemini_api_key)
        except Exception:
            return None

        flash_system = (
            "你是持仓风险诊断师，专注于识别已持仓股票的盘中价格行为。"
            "你的任务是判断当前触发的技术信号是否构成真实有效的持仓风险，"
            "还是临时噪声（假突破/洗盘/尾盘回补）。"
            "输出必须明确判断：真实风险/噪声/不确定，附价格判断依据。禁止分析基本面/舆情。"
        )
        flash_prompt = (
            f"{name}（{code}）触发监控警报，请快速诊断当前技术信号有效性。\n\n"
            f"【持仓背景】成本价:{cost_price} | 现价:{current_price:.2f} | 浮盈:{pnl_pct:+.1f}% | "
            f"持仓{holding_days}天 | 持仓周期:{effective_horizon}\n"
            f"【触发事件】{trigger_desc}\n"
            f"【实时分时技术快照】{intraday_text}\n"
            f"{regime_hint}\n\n"
            f"请回答（≤150字，纯技术分析）：\n"
            f"①破位有效性判断（真实/噪声/不确定）及核心依据（1-2个信号）；\n"
            f"②当前盘中支撑/压力关键价位；\n"
            f"③若为真实风险，失效条件是什么（例：收复X价=信号失效）。"
        )

        model_name = getattr(cfg, 'gemini_model_when_cached', None) or getattr(cfg, 'gemini_model', None)
        if not model_name:
            return None
        model = genai.GenerativeModel(model_name, system_instruction=flash_system)
        api_timeout = getattr(cfg, 'gemini_request_timeout', 120)
        with ThreadPoolExecutor(max_workers=1) as tp:
            fut = tp.submit(model.generate_content, flash_prompt)
            resp = fut.result(timeout=min(api_timeout, 20))
        text = (resp.text or '').strip()
        return text[:800] if text else None
    except Exception as e:
        logger.debug(f"[monitor_analyzer] Flash诊断失败: {e}")
        return None


def _run_monitor_pro(
    code: str, name: str, trigger_type: str, trigger_desc: str,
    cost_price: float, current_price: float, atr_stop: float,
    pnl_pct: float, holding_days: int, effective_horizon: str,
    intraday_text: str, flash_result: Optional[str],
    f10_brief: str, news_brief: str, last_score: Any, last_advice: str,
    stale_note: str, hours_ago: float, news_stale: str,
    regime_hint: str, horizon_conflict: str,
) -> Optional[Dict[str, Any]]:
    """运行监控专属 Pro 决策（三选一操作建议 + JSON输出）。"""
    try:
        from src.config import Config
        from concurrent.futures import ThreadPoolExecutor
        cfg = Config()
        try:
            import google.generativeai as genai
            genai.configure(api_key=cfg.gemini_api_key)
        except Exception:
            return None

        tech_section = (
            f"【独立技术分析师诊断】\n{flash_result}"
            if flash_result else
            f"【实时分时技术快照】\n{intraday_text}"
        )

        fundamental_section = ""
        if f10_brief or news_brief:
            fundamental_section = (
                f"\n{stale_note}\n"
                f"【基本面摘要（{hours_ago:.0f}h前）】{f10_brief}\n"
                f"【近期舆情】{news_brief} {news_stale}"
            )

        pro_system = (
            "你是一位专业基金经理，正在处理一个持仓中的紧急风险事件。"
            "你需要快速做出三选一的操作决策，并给出具体的操作价格和后续观察点。"
            "禁止给出模糊建议，必须给出具体价格数字。"
        )

        pro_prompt = f"""{name}（{code}）持仓监控触发，需要你立即做出操作决策。

【持仓状态】
成本价: {cost_price} | 当前价: {current_price:.2f} | 浮盈: {pnl_pct:+.1f}%
持仓天数: {holding_days}天 | 持仓周期意图: {effective_horizon}
上次评分: {last_score} | 上次建议: {last_advice}

【触发事件】
{trigger_desc}
{regime_hint}
{horizon_conflict}

{tech_section}
{fundamental_section}

【决策要求】
从以下三选一，给出具体操作价格：
A. 立即止损出场（给出执行价格）
B. 下调止损线继续持仓（给出新止损价 + 下一个观察点）
C. 无需操作，维持现有策略（给出反驳当前触发信号的理由）

输出严格的 JSON（无 markdown 包裹）：
{{"decision": "A/B/C", "action_price": 数字或null, "new_stop": 数字或null, "next_checkpoint": "价格或日期", "reasoning": "≤60字"}}"""

        model_name = getattr(cfg, 'gemini_model', None)
        if not model_name:
            return None
        model = genai.GenerativeModel(model_name, system_instruction=pro_system)
        api_timeout = getattr(cfg, 'gemini_request_timeout', 120)
        with ThreadPoolExecutor(max_workers=1) as tp:
            fut = tp.submit(model.generate_content, pro_prompt)
            resp = fut.result(timeout=min(api_timeout, 30))
        text = (resp.text or '').strip()
        text = text.lstrip('`').removeprefix('json').strip().rstrip('`').strip()
        result = json.loads(text)
        return {
            'decision': result.get('decision', ''),
            'action_price': result.get('action_price'),
            'new_stop': result.get('new_stop'),
            'next_checkpoint': str(result.get('next_checkpoint', '')),
            'reasoning': str(result.get('reasoning', '')),
        }
    except Exception as e:
        logger.debug(f"[monitor_analyzer] Pro诊断失败: {e}")
        return None


def _push_diagnose_result(
    code: str, name: str, trigger_desc: str, result: Dict[str, Any]
) -> None:
    """推送监控诊断结果到 PushPlus。"""
    try:
        decision = result.get('decision', '?')
        decision_label = {'A': '🔴 立即止损出场', 'B': '🟡 下调止损继续持仓', 'C': '🟢 维持现有策略'}.get(decision, decision)
        title = f"📊 监控诊断：{name}({code}) → {decision_label}"
        content = (
            f"## {title}\n\n"
            f"**触发事件**：{trigger_desc}\n\n"
            f"**决策**：{decision_label}\n"
        )
        if result.get('action_price'):
            content += f"**操作价格**：{result['action_price']:.2f}\n"
        if result.get('new_stop'):
            content += f"**新止损线**：{result['new_stop']:.2f}\n"
        if result.get('next_checkpoint'):
            content += f"**下一观察点**：{result['next_checkpoint']}\n"
        if result.get('reasoning'):
            content += f"\n**诊断理由**：{result['reasoning']}"
        from src.notification import NotificationManager
        nm = NotificationManager.get_instance()
        nm.send_to_pushplus(content=content, title=title)
    except Exception as e:
        logger.debug(f"[monitor_analyzer] 诊断结果推送失败: {e}")

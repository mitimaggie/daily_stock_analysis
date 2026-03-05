# -*- coding: utf-8 -*-
"""
组合风险服务：计算持仓组合的 Beta 和最大回撤（MaxDD），供 LLM prompt 注入。

Beta = Cov(stock_returns, market_returns) / Var(market_returns)
组合 Beta = 各股 Beta 的市值加权平均。

MaxDD 控制：
  - 基于持仓成本价与当前价格计算组合浮盈
  - 在 data_cache 中追踪历史峰值（无TTL，只升不降）
  - 当回撤超阈值时返回 guard_level 触发分析层保守覆盖

数据源：stock_daily + index_daily（上证指数）
缓存：内存 TTL=1h（Beta）；data_cache 峰值无过期（MaxDD）
"""

import json
import logging
import time
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

_BETA_CACHE: Dict[str, Any] = {}
_BETA_CACHE_TTL_SECONDS = 3600  # 1h
_BENCHMARK_CODE = "上证指数"
_LOOKBACK_DAYS = 60


def _compute_beta(stock_returns: List[float], market_returns: List[float]) -> Optional[float]:
    """计算单只股票相对市场的 Beta。两组序列必须对齐。"""
    if len(stock_returns) < 20 or len(market_returns) < 20:
        return None
    n = min(len(stock_returns), len(market_returns))
    s = stock_returns[-n:]
    m = market_returns[-n:]

    mean_s = sum(s) / n
    mean_m = sum(m) / n
    cov = sum((s[i] - mean_s) * (m[i] - mean_m) for i in range(n)) / (n - 1)
    var_m = sum((m[i] - mean_m) ** 2 for i in range(n)) / (n - 1)
    if var_m < 1e-10:
        return None
    return round(cov / var_m, 3)


def calculate_portfolio_beta(
    holdings: List[Dict[str, Any]],
    lookback: int = _LOOKBACK_DAYS,
) -> Optional[Dict[str, Any]]:
    """
    计算持仓组合整体 Beta。

    Args:
        holdings: list of {code, cost_price, shares, name} from list_portfolio()
        lookback: 历史天数（默认60天）

    Returns:
        {
            "portfolio_beta": float,
            "holdings_beta": {code: beta},
            "benchmark": str,
            "data_days": int,
        }
        或 None（数据不足时）
    """
    cache_key = f"beta_{','.join(sorted(h['code'] for h in holdings))}_{lookback}"
    cached = _BETA_CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _BETA_CACHE_TTL_SECONDS:
        logger.debug("[Beta] 命中内存缓存")
        return cached["data"]

    try:
        from src.storage import DatabaseManager
        db = DatabaseManager.get_instance()

        market_series = db.get_index_returns(index_name=_BENCHMARK_CODE, days=lookback + 5)
        if market_series.empty or len(market_series) < 20:
            logger.debug(f"[Beta] 指数数据不足: {len(market_series)} 条")
            return None
        market_returns = market_series.tolist()

        holdings_beta: Dict[str, float] = {}
        total_weight = 0.0
        weighted_beta_sum = 0.0

        for h in holdings:
            code = h.get("code")
            if not code:
                continue
            try:
                stock_series = db.get_stock_returns(code=code, days=lookback + 5)
                if stock_series.empty or len(stock_series) < 20:
                    logger.debug(f"[Beta] {code} 数据不足，跳过")
                    continue
                stock_returns = stock_series.tolist()
                beta = _compute_beta(stock_returns, market_returns)
                if beta is None:
                    continue
                holdings_beta[code] = beta

                shares = float(h.get("shares") or 0)
                cost_price = float(h.get("cost_price") or 0)
                weight = shares * cost_price
                if weight > 0:
                    weighted_beta_sum += beta * weight
                    total_weight += weight
            except Exception as e:
                logger.debug(f"[Beta] {code} 计算失败: {e}")
                continue

        if not holdings_beta:
            return None

        portfolio_beta = (
            round(weighted_beta_sum / total_weight, 3)
            if total_weight > 0
            else round(sum(holdings_beta.values()) / len(holdings_beta), 3)
        )

        result = {
            "portfolio_beta": portfolio_beta,
            "holdings_beta": holdings_beta,
            "benchmark": _BENCHMARK_CODE,
            "data_days": len(market_returns),
        }
        _BETA_CACHE[cache_key] = {"ts": time.time(), "data": result}
        logger.info(f"[Beta] 组合Beta={portfolio_beta}，覆盖{len(holdings_beta)}/{len(holdings)}只持仓")
        return result

    except Exception as e:
        logger.warning(f"[Beta] 计算失败: {e}")
        return None


_DD_GUARD_LEVELS = [
    (-15.0, "halt",      "🚨 组合回撤>15%：暂停所有新建仓，仅允许止损/减仓操作"),
    (-10.0, "defensive", "⚠️ 组合回撤10-15%：所有买入→观望，加仓→维持，已持仓保守止损"),
    (-5.0,  "caution",   "📉 组合回撤5-10%：降低仓位上限，止损条件收紧，买入需更高确定性"),
    (0.0,   "normal",    ""),
]


def calculate_portfolio_drawdown(
    holdings: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    计算组合当前浮盈率，追踪历史峰值，输出回撤状态与 guard_level。

    使用 stock_daily 最新收盘价 + 持仓成本价计算组合浮盈。
    峰值记录保存在 data_cache（cache_type='portfolio_peak'），只升不降。

    Returns:
        {
            "portfolio_return_pct": float,   # 组合浮盈率(%)
            "peak_return_pct": float,        # 历史最高浮盈率(%)
            "drawdown_pct": float,           # 当前回撤(%，≤0)
            "guard_level": str,              # "normal"|"caution"|"defensive"|"halt"
            "guard_desc": str,               # 操作提示文字
            "holdings_return": dict,         # {code: pct}
        }
        或 None（无持仓/数据不足）
    """
    if not holdings:
        return None

    try:
        from src.storage import DatabaseManager
        db = DatabaseManager.get_instance()

        total_cost = 0.0
        total_value = 0.0
        holdings_return: Dict[str, float] = {}

        for h in holdings:
            code = h.get("code")
            shares = float(h.get("shares") or 0)
            cost_price = float(h.get("cost_price") or 0)
            if not code or shares <= 0 or cost_price <= 0:
                continue
            try:
                latest_list = db.get_latest_data(code)
                if not latest_list:
                    continue
                latest = latest_list[-1] if isinstance(latest_list, list) else latest_list
                current_price = float(getattr(latest, 'close', 0) or getattr(latest, 'price', 0) or 0)
                if current_price <= 0:
                    continue
                pos_cost = shares * cost_price
                pos_value = shares * current_price
                total_cost += pos_cost
                total_value += pos_value
                holdings_return[code] = round((current_price / cost_price - 1) * 100, 2)
            except Exception as _he:
                logger.debug(f"[MaxDD] {code} 价格获取失败: {_he}")
                continue

        if total_cost <= 0:
            return None

        portfolio_return_pct = round((total_value / total_cost - 1) * 100, 2)

        # 读取历史峰值（只升不降）
        PEAK_CACHE_TYPE = "portfolio_peak"
        PEAK_CACHE_KEY = "global"
        peak_return_pct = portfolio_return_pct
        try:
            cached = db.get_data_cache(PEAK_CACHE_TYPE, PEAK_CACHE_KEY, ttl_hours=365 * 24)
            if cached:
                peak_data = json.loads(cached)
                stored_peak = float(peak_data.get("peak_return_pct", portfolio_return_pct))
                peak_return_pct = max(stored_peak, portfolio_return_pct)
        except Exception as _pe:
            logger.debug(f"[MaxDD] 峰值读取失败: {_pe}")

        # 更新峰值（若当前浮盈刷新历史高点）
        if portfolio_return_pct >= peak_return_pct:
            try:
                db.save_data_cache(
                    PEAK_CACHE_TYPE, PEAK_CACHE_KEY,
                    json.dumps({"peak_return_pct": portfolio_return_pct}, ensure_ascii=False)
                )
            except Exception as _se:
                logger.debug(f"[MaxDD] 峰值保存失败: {_se}")

        drawdown_pct = round(portfolio_return_pct - peak_return_pct, 2)

        guard_level = "normal"
        guard_desc = ""
        for threshold, level, desc in _DD_GUARD_LEVELS:
            if drawdown_pct <= threshold:
                guard_level = level
                guard_desc = desc
                break

        result = {
            "portfolio_return_pct": portfolio_return_pct,
            "peak_return_pct": peak_return_pct,
            "drawdown_pct": drawdown_pct,
            "guard_level": guard_level,
            "guard_desc": guard_desc,
            "holdings_return": holdings_return,
        }
        logger.info(
            f"[MaxDD] 组合浮盈={portfolio_return_pct:+.1f}% 峰值={peak_return_pct:+.1f}% "
            f"回撤={drawdown_pct:+.1f}% guard={guard_level}"
        )
        return result

    except Exception as e:
        logger.warning(f"[MaxDD] 计算失败: {e}")
        return None

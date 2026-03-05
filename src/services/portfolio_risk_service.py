# -*- coding: utf-8 -*-
"""
组合风险服务：计算持仓组合的 Beta，供 LLM prompt 注入。

Beta = Cov(stock_returns, market_returns) / Var(market_returns)
组合 Beta = 各股 Beta 的市值加权平均。

数据源：stock_daily + index_daily（上证指数）
缓存：内存 TTL=1h，避免每次分析批次重算。
"""

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

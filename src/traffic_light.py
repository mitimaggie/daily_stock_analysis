# -*- coding: utf-8 -*-
"""
===================================
红绿灯信号模块
===================================

职责：
1. 基于市场情绪温度计算操作信号（积极/谨慎/观望/空仓）
2. 平滑机制防止信号剧烈跳变
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.market_sentiment import MarketSentiment

logger = logging.getLogger(__name__)

SIGNAL_LEVELS: Dict[str, int] = {
    "active": 4,
    "cautious": 3,
    "wait": 2,
    "cash": 1,
}

SIGNAL_META: Dict[str, Dict[str, str]] = {
    "active":   {"label": "积极", "color": "green"},
    "cautious": {"label": "谨慎", "color": "yellow"},
    "wait":     {"label": "观望", "color": "orange"},
    "cash":     {"label": "空仓", "color": "red"},
}

_LEVEL_TO_SIGNAL: Dict[int, str] = {v: k for k, v in SIGNAL_LEVELS.items()}


def _calc_raw_score(sentiment: MarketSentiment,
                    deviation: Optional[float]) -> float:
    """基于情绪温度和修正因子计算原始综合得分 (0-100)"""
    score = float(sentiment.temperature)

    if deviation is not None:
        if deviation > 1.5:
            score += 5
        elif deviation < -1.5:
            score -= 10

    total_limits = sentiment.limit_up_count + sentiment.limit_down_count
    if total_limits > 0:
        up_ratio = sentiment.limit_up_count / total_limits
        if up_ratio > 0.7:
            score += 5
        elif up_ratio < 0.3:
            score -= 10

    if sentiment.broken_limit_rate > 50:
        score -= 10
    elif sentiment.broken_limit_rate > 30:
        score -= 5

    return max(0.0, min(100.0, score))


def _score_to_signal(score: float) -> str:
    """将得分映射为四色信号"""
    if score >= 70:
        return "active"
    elif score >= 45:
        return "cautious"
    elif score >= 25:
        return "wait"
    return "cash"


def _build_reason(sentiment: MarketSentiment) -> str:
    """生成一句话理由"""
    parts: List[str] = []
    if sentiment.temperature_label:
        parts.append(f"市场情绪{sentiment.temperature_label}")
    if sentiment.limit_up_count > 0:
        parts.append(f"涨停{sentiment.limit_up_count}家")
    if sentiment.limit_down_count > 0:
        parts.append(f"跌停{sentiment.limit_down_count}家")
    if sentiment.broken_limit_rate > 30:
        parts.append(f"炸板率{sentiment.broken_limit_rate:.0f}%")
    return "，".join(parts) if parts else "数据不足"


def _smooth_signal(today_signal: str, db: Any, today_str: str,
                   raw_score: float = 50.0) -> str:
    """平滑：防止信号跳变超过 1 级；极端行情（分数变化>=30）允许跳变 2 级"""
    prev_cached = None
    for offset in range(1, 8):
        prev_str = (datetime.now() - timedelta(days=offset)).strftime('%Y-%m-%d')
        try:
            prev_cached = db.get_data_cache("traffic_light", prev_str, ttl_hours=48 + offset * 24)
        except Exception:
            continue
        if prev_cached:
            break

    if not prev_cached:
        return today_signal

    try:
        prev_data = json.loads(prev_cached)
    except (json.JSONDecodeError, TypeError):
        return today_signal

    yesterday_signal = prev_data.get("signal", "")
    prev_score = prev_data.get("score", 50.0)
    today_level = SIGNAL_LEVELS.get(today_signal, 3)
    yesterday_level = SIGNAL_LEVELS.get(yesterday_signal, 3)

    score_delta = abs(raw_score - prev_score)
    if score_delta >= 30:
        if abs(today_level - yesterday_level) <= 2:
            return today_signal
        if today_level > yesterday_level:
            smoothed_level = yesterday_level + 2
        else:
            smoothed_level = yesterday_level - 2
        return _LEVEL_TO_SIGNAL.get(smoothed_level, today_signal)

    if abs(today_level - yesterday_level) <= 1:
        return today_signal

    if today_level > yesterday_level:
        smoothed_level = yesterday_level + 1
    else:
        smoothed_level = yesterday_level - 1

    return _LEVEL_TO_SIGNAL.get(smoothed_level, today_signal)


def compute_traffic_light(sentiment: MarketSentiment,
                          deviation: Optional[float],
                          db: Any) -> Dict[str, Any]:
    """计算红绿灯信号

    Args:
        sentiment: 市场情绪快照
        deviation: 温度偏离度（标准差倍数），可为 None
        db: DatabaseManager 实例

    Returns:
        {
            "signal": "active" | "cautious" | "wait" | "cash",
            "signal_label": str,
            "signal_color": str,
            "reason": str,
            "score": float,
        }
    """
    score = _calc_raw_score(sentiment, deviation)
    raw_signal = _score_to_signal(score)

    today_str = datetime.now().strftime('%Y-%m-%d')
    signal = _smooth_signal(raw_signal, db, today_str, raw_score=score)

    meta = SIGNAL_META.get(signal, SIGNAL_META["cautious"])
    reason = _build_reason(sentiment)

    result: Dict[str, Any] = {
        "signal": signal,
        "signal_label": meta["label"],
        "signal_color": meta["color"],
        "reason": reason,
        "score": round(score, 1),
    }

    try:
        db.save_data_cache("traffic_light", today_str,
                           json.dumps(result, ensure_ascii=False))
    except Exception as e:
        logger.debug(f"保存红绿灯缓存失败: {e}")

    return result

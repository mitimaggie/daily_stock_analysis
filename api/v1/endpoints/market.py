# -*- coding: utf-8 -*-
"""
===================================
市场概览 API
===================================

职责：
1. 提供 GET /api/v1/market/overview 获取市场概览数据（含红绿灯信号）
2. 提供 GET /api/v1/market/todo-list 获取今日操作清单
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/overview")
async def get_market_overview() -> Dict[str, Any]:
    """获取市场概览数据：情绪温度、涨跌停统计、概念热度Top10、红绿灯信号"""
    from dataclasses import asdict

    from src.market_sentiment import get_market_sentiment_cached, calc_temperature_deviation
    from src.traffic_light import compute_traffic_light
    from data_provider.concept_fetcher import fetch_concept_daily
    from src.storage import DatabaseManager
    from src.config import Config

    config = Config.get_instance()
    db = DatabaseManager.get_instance()

    result: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "sentiment": None,
        "concepts": None,
        "temperature_deviation": None,
        "traffic_light": None,
    }

    sentiment = None
    deviation = None

    try:
        sentiment = get_market_sentiment_cached(db)
        if sentiment:
            raw = asdict(sentiment)
            raw["limit_up"] = raw.get("limit_up_count", 0)
            raw["limit_down"] = raw.get("limit_down_count", 0)
            raw["broken"] = raw.get("broken_limit_count", 0)
            raw["broken_rate"] = raw.get("broken_limit_rate", 0.0)
            raw["emotion_temp"] = raw.get("temperature", 50)
            raw["emotion_label"] = raw.get("temperature_label", "中性")
            raw["advance_count"] = raw.get("up_count", 0)
            raw["decline_count"] = raw.get("down_count", 0)
            result["sentiment"] = raw
            deviation = calc_temperature_deviation(sentiment.temperature, db)
            result["temperature_deviation"] = deviation
    except Exception as e:
        logger.warning(f"获取市场情绪失败: {e}")

    if sentiment:
        try:
            result["traffic_light"] = compute_traffic_light(sentiment, deviation, db)
        except Exception as e:
            logger.warning(f"计算红绿灯信号失败: {e}")

    try:
        concepts = fetch_concept_daily(db, config)
        if concepts:
            result["concepts"] = concepts[:10]
    except Exception as e:
        logger.warning(f"获取概念热度失败: {e}")

    return result


class ConceptHoldingsRequest(BaseModel):
    codes: List[str]

@router.post("/concept-holdings", summary="持仓股概念关联查询")
async def api_concept_holdings(req: ConceptHoldingsRequest) -> Dict[str, Any]:
    """查询持仓股属于哪些概念"""
    from src.storage import DatabaseManager

    db = DatabaseManager.get_instance()
    mappings: Dict[str, List[str]] = {}
    for code in req.codes:
        concepts = db.get_stock_concepts(code)
        mappings[code] = [c.concept_name for c in concepts] if concepts else []
    return {"mappings": mappings}


@router.get("/todo-list")
async def get_todo_list() -> Dict[str, Any]:
    """获取今日操作清单（基于持仓和关注股）"""
    from sqlalchemy import select, desc, and_
    from src.storage import DatabaseManager, Portfolio, AnalysisHistory
    from src.config import Config

    db = DatabaseManager.get_instance()
    todos: List[Dict[str, Any]] = []

    try:
        with db.get_session() as session:
            holdings = session.execute(
                select(Portfolio).order_by(Portfolio.created_at)
            ).scalars().all()

            for h in holdings:
                _check_stop_loss(h, session, todos)
                _check_score_change(h, session, todos)
    except Exception as e:
        logger.warning(f"获取持仓预警失败: {e}")

    return {
        "timestamp": datetime.now().isoformat(),
        "todos": todos,
        "count": len(todos),
    }


def _check_stop_loss(holding: Any, session: Any,
                     todos: List[Dict[str, Any]]) -> None:
    """检查单只持仓的止损预警，有触发则追加到 todos 列表"""
    from sqlalchemy import select, desc
    from src.storage import AnalysisHistory

    code = holding.code
    name = holding.name or code

    try:
        latest = session.execute(
            select(AnalysisHistory)
            .where(AnalysisHistory.code == code)
            .order_by(desc(AnalysisHistory.created_at))
            .limit(1)
        ).scalar_one_or_none()
    except Exception:
        return

    if not latest or not latest.raw_result:
        return

    try:
        result_data = json.loads(latest.raw_result)
    except (json.JSONDecodeError, TypeError):
        return

    dashboard = result_data.get("dashboard", {})
    quant = dashboard.get("quant_extras", {})

    if quant.get("stop_loss_breached"):
        todos.append({
            "type": "stop_loss",
            "priority": "high",
            "code": code,
            "name": name,
            "message": f"{name} 已触发止损位",
            "detail": quant.get("stop_loss_breach_detail", ""),
        })
        return

    if holding.atr_stop_loss and latest.stop_loss:
        try:
            ctx = json.loads(latest.context_snapshot) if latest.context_snapshot else {}
            today_data = ctx.get("today", {})
            current_close = today_data.get("close")
            if current_close and current_close <= holding.atr_stop_loss:
                todos.append({
                    "type": "stop_loss",
                    "priority": "high",
                    "code": code,
                    "name": name,
                    "message": f"{name} 接近ATR止损位 {holding.atr_stop_loss:.2f}",
                    "detail": f"当前收盘 {current_close:.2f}，ATR止损 {holding.atr_stop_loss:.2f}",
                })
        except (json.JSONDecodeError, TypeError, ValueError):
            pass


def _check_score_change(holding: Any, session: Any,
                        todos: List[Dict[str, Any]]) -> None:
    """检查评分大幅变化（最近两次评分差 >= 10 分）"""
    from sqlalchemy import select, desc
    from src.storage import AnalysisHistory

    code = holding.code
    name = holding.name or code

    try:
        rows = session.execute(
            select(AnalysisHistory.sentiment_score, AnalysisHistory.created_at)
            .where(AnalysisHistory.code == code)
            .order_by(desc(AnalysisHistory.created_at))
            .limit(2)
        ).all()
    except Exception:
        return

    if len(rows) < 2 or rows[0][0] is None or rows[1][0] is None:
        return

    latest_score, prev_score = rows[0][0], rows[1][0]
    diff = latest_score - prev_score
    if abs(diff) < 10:
        return

    direction = "上升" if diff > 0 else "下降"
    priority = "medium" if abs(diff) < 15 else "high"
    todos.append({
        "type": "score_change",
        "priority": priority,
        "code": code,
        "name": name,
        "message": f"{name} 评分大幅{direction}",
        "detail": f"评分从 {prev_score} → {latest_score}（{'+' if diff > 0 else ''}{diff}分）",
    })

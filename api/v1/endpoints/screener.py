# -*- coding: utf-8 -*-
"""股票筛选 API — 从最近分析历史中按条件筛选高分股票"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.storage import DatabaseManager, AnalysisHistory
from sqlalchemy import select, and_, desc

logger = logging.getLogger(__name__)
router = APIRouter()


class ScreenerResult(BaseModel):
    code: str
    name: Optional[str] = None
    score: Optional[int] = None
    advice: Optional[str] = None
    analyzed_at: Optional[str] = None


class ScreenerResponse(BaseModel):
    total: int
    results: List[ScreenerResult]


@router.get("/screen", response_model=ScreenerResponse, summary="股票筛选")
async def screen_stocks(
    min_score: int = Query(default=75, ge=0, le=100, description="最低评分"),
    max_score: int = Query(default=100, ge=0, le=100, description="最高评分"),
    days: int = Query(default=3, ge=1, le=30, description="回溯天数"),
    advice_filter: Optional[str] = Query(default=None, description="操作建议过滤，如'买入'"),
    limit: int = Query(default=20, ge=1, le=50, description="返回条数"),
) -> ScreenerResponse:
    """从最近分析历史中筛选符合条件的股票"""
    db = DatabaseManager.get_instance()
    cutoff = datetime.now() - timedelta(days=days)

    with db.get_session() as session:
        query = select(AnalysisHistory).where(
            and_(
                AnalysisHistory.created_at >= cutoff,
                AnalysisHistory.sentiment_score >= min_score,
                AnalysisHistory.sentiment_score <= max_score,
            )
        ).order_by(desc(AnalysisHistory.sentiment_score))

        if advice_filter:
            query = query.where(AnalysisHistory.operation_advice.contains(advice_filter))

        records = session.execute(query.limit(limit * 3)).scalars().all()

    seen: dict = {}
    for r in records:
        if r.code not in seen or (r.sentiment_score or 0) > (seen[r.code].sentiment_score or 0):
            seen[r.code] = r

    results = []
    for r in sorted(seen.values(), key=lambda x: x.sentiment_score or 0, reverse=True)[:limit]:
        results.append(ScreenerResult(
            code=r.code,
            name=r.name,
            score=r.sentiment_score,
            advice=r.operation_advice,
            analyzed_at=r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else None,
        ))

    return ScreenerResponse(total=len(results), results=results)

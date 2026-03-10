# -*- coding: utf-8 -*-
"""
===================================
股票数据接口
===================================

职责：
1. 提供 GET /api/v1/stocks/{code}/quote 实时行情接口
2. 提供 GET /api/v1/stocks/{code}/history 历史行情接口
"""

import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.v1.schemas.stocks import (
    StockQuote,
    StockHistoryResponse,
    KLineData,
)
from api.v1.schemas.common import ErrorResponse
from src.services.stock_service import StockService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/{stock_code}/quote",
    response_model=StockQuote,
    responses={
        200: {"description": "行情数据"},
        404: {"description": "股票不存在", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取股票实时行情",
    description="获取指定股票的最新行情数据"
)
def get_stock_quote(stock_code: str) -> StockQuote:
    """
    获取股票实时行情
    
    获取指定股票的最新行情数据
    
    Args:
        stock_code: 股票代码（如 600519、00700、AAPL）
        
    Returns:
        StockQuote: 实时行情数据
        
    Raises:
        HTTPException: 404 - 股票不存在
    """
    try:
        service = StockService()
        
        # 使用 def 而非 async def，FastAPI 自动在线程池中执行
        result = service.get_realtime_quote(stock_code)
        
        if result is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "message": f"未找到股票 {stock_code} 的行情数据"
                }
            )
        
        return StockQuote(
            stock_code=result.get("stock_code", stock_code),
            stock_name=result.get("stock_name"),
            current_price=result.get("current_price", 0.0),
            change=result.get("change"),
            change_percent=result.get("change_percent"),
            open=result.get("open"),
            high=result.get("high"),
            low=result.get("low"),
            prev_close=result.get("prev_close"),
            volume=result.get("volume"),
            amount=result.get("amount"),
            update_time=result.get("update_time")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取实时行情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取实时行情失败: {str(e)}"
            }
        )


@router.get(
    "/{stock_code}/history",
    response_model=StockHistoryResponse,
    responses={
        200: {"description": "历史行情数据"},
        422: {"description": "不支持的周期参数", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取股票历史行情",
    description="获取指定股票的历史 K 线数据"
)
def get_stock_history(
    stock_code: str,
    period: str = Query("daily", description="K 线周期", pattern="^(daily|weekly|monthly)$"),
    days: int = Query(30, ge=1, le=365, description="获取天数")
) -> StockHistoryResponse:
    """
    获取股票历史行情
    
    获取指定股票的历史 K 线数据
    
    Args:
        stock_code: 股票代码
        period: K 线周期 (daily/weekly/monthly)
        days: 获取天数
        
    Returns:
        StockHistoryResponse: 历史行情数据
    """
    try:
        service = StockService()
        
        # 使用 def 而非 async def，FastAPI 自动在线程池中执行
        result = service.get_history_data(
            stock_code=stock_code,
            period=period,
            days=days
        )
        
        # 转换为响应模型
        data = [
            KLineData(
                date=item.get("date"),
                open=item.get("open"),
                high=item.get("high"),
                low=item.get("low"),
                close=item.get("close"),
                volume=item.get("volume"),
                amount=item.get("amount"),
                change_percent=item.get("change_percent")
            )
            for item in result.get("data", [])
        ]
        
        return StockHistoryResponse(
            stock_code=stock_code,
            stock_name=result.get("stock_name"),
            period=period,
            data=data
        )
    
    except ValueError as e:
        # period 参数不支持的错误（如 weekly/monthly）
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unsupported_period",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"获取历史行情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取历史行情失败: {str(e)}"
            }
        )


class BatchScoreTrendRequest(BaseModel):
    """批量获取评分趋势的请求体"""

    codes: List[str] = Field(..., max_length=20, description="股票代码列表，最多20只")
    days: int = Field(default=5, ge=3, le=30, description="回溯天数")


@router.post(
    "/batch-score-trend",
    summary="批量获取多只股票评分趋势",
    description="一次请求获取多只股票的历史量化评分趋势，用于持仓页 MonitorCard 批量展示"
)
def batch_score_trend(req: BatchScoreTrendRequest):
    """批量获取股票评分趋势，复用 get_score_trend 逻辑"""
    try:
        from src.storage import DatabaseManager

        db = DatabaseManager()
        results = {}
        for code in req.codes:
            trend = db.get_score_trend(code, days=req.days)
            results[code] = trend
        return {"results": results}
    except Exception as e:
        logger.error(f"批量获取评分趋势失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": str(e)},
        )


@router.get(
    "/{stock_code}/score-trend",
    summary="获取股票评分历史趋势",
    description="获取指定股票的历史量化评分趋势（连续上升/下降天数、拐点信号）"
)
def get_score_trend(
    stock_code: str,
    days: int = Query(default=10, ge=3, le=30, description="回溯天数"),
):
    """获取股票评分趋势，含连续上升/下降天数、趋势方向和拐点信号"""
    try:
        from src.storage import DatabaseManager
        db = DatabaseManager()
        trend = db.get_score_trend(stock_code, days=days)
        return {"stock_code": stock_code, "trend": trend}
    except Exception as e:
        logger.error(f"获取评分趋势失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": str(e)}
        )


@router.get(
    "/{stock_code}/last-skill",
    summary="获取上次使用的AI框架",
    description="查询该股票上一次分析使用的AI skill名称，用于框架切换提示"
)
def get_last_skill(stock_code: str):
    """获取上次分析使用的AI框架，如果与本次不同则前端展示切换提示"""
    try:
        from sqlalchemy import text
        from src.storage import DatabaseManager
        db = DatabaseManager()
        session = db.get_session()
        try:
            row = session.execute(text("""
                SELECT json_extract(raw_result, '$.skill_used') as skill
                FROM analysis_history
                WHERE code = :code
                  AND raw_result IS NOT NULL
                  AND raw_result != 'null'
                ORDER BY created_at DESC
                LIMIT 2
            """), {"code": stock_code}).fetchall()
        finally:
            session.close()
        skills = [r[0] for r in row if r[0]]
        return {
            "stock_code": stock_code,
            "last_skill": skills[0] if skills else None,
            "prev_skill": skills[1] if len(skills) > 1 else None,
        }
    except Exception as e:
        logger.error(f"获取上次AI框架失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": str(e)}
        )


@router.get(
    "/{stock_code}/timeframe-winrates",
    summary="获取多时间线历史胜率",
    description="基于backtest_simulated数据，按当前信号的评分段+周线背景返回5/10/20日历史胜率"
)
def get_timeframe_winrates(
    stock_code: str,
    signal_score: int = Query(default=0, ge=0, le=100, description="当前信号评分"),
    weekly_trend: str = Query(default="", description="周线趋势（多头/弱多头/震荡/弱空头/空头）"),
    resonance_level: str = Query(default="", description="共振级别"),
):
    """
    查询 backtest_simulated，按评分段+周线背景统计5/10/20日胜率。
    用于在报告决策卡下方展示历史同类信号的多时间线胜率。
    """
    try:
        from sqlalchemy import text
        from src.storage import DatabaseManager
        db = DatabaseManager()

        # 确定评分段
        if signal_score >= 85:
            score_min, score_max = 85, 200
        elif signal_score >= 78:
            score_min, score_max = 78, 84
        elif signal_score >= 75:
            score_min, score_max = 75, 77
        else:
            score_min, score_max = 0, 74

        # 按评分段+周线背景查询
        session = db.get_session()
        try:
            rows = session.execute(text("""
                SELECT
                    COUNT(*) as n,
                    ROUND(AVG(CASE WHEN actual_pct_5d > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) as wr5d,
                    ROUND(AVG(actual_pct_5d), 2) as avg5d,
                    ROUND(AVG(CASE WHEN actual_pct_10d > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) as wr10d,
                    ROUND(AVG(actual_pct_10d), 2) as avg10d,
                    ROUND(AVG(CASE WHEN actual_pct_20d > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) as wr20d,
                    ROUND(AVG(actual_pct_20d), 2) as avg20d
                FROM backtest_simulated
                WHERE backtest_filled = 1
                  AND actual_pct_5d IS NOT NULL
                  AND actual_pct_10d IS NOT NULL
                  AND actual_pct_20d IS NOT NULL
                  AND signal_score BETWEEN :score_min AND :score_max
                  AND (:weekly_trend = '' OR weekly_trend = :weekly_trend)
            """), {"score_min": score_min, "score_max": score_max, "weekly_trend": weekly_trend}).fetchone()
        finally:
            session.close()

        if not rows or rows[0] == 0:
            return {
                "stock_code": stock_code,
                "signal_score": signal_score,
                "weekly_trend": weekly_trend,
                "n": 0,
                "wr5d": None, "avg5d": None,
                "wr10d": None, "avg10d": None,
                "wr20d": None, "avg20d": None,
                "best_horizon": None,
            }

        n, wr5d, avg5d, wr10d, avg10d, wr20d, avg20d = rows

        # 找最优持股窗口（胜率最高的时间线）
        winrates = {"5d": wr5d or 0, "10d": wr10d or 0, "20d": wr20d or 0}
        best_horizon = max(winrates, key=winrates.get)

        return {
            "stock_code": stock_code,
            "signal_score": signal_score,
            "score_range": f"{score_min}-{score_max if score_max < 200 else '+'}",
            "weekly_trend": weekly_trend,
            "n": n,
            "wr5d": wr5d, "avg5d": avg5d,
            "wr10d": wr10d, "avg10d": avg10d,
            "wr20d": wr20d, "avg20d": avg20d,
            "best_horizon": best_horizon,
        }
    except Exception as e:
        logger.error(f"获取多时间线胜率失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": str(e)}
        )

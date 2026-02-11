# -*- coding: utf-8 -*-
"""
回测 API 端点（借鉴上游 #269）

提供回测执行和结果查询接口，供 WebUI 展示回测统计。
"""

import logging
from typing import Optional
from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/run")
async def run_backtest(lookback_days: int = Query(60, ge=7, le=365, description="回溯天数")):
    """执行回测并返回统计报告"""
    try:
        from src.backtest import BacktestRunner
        runner = BacktestRunner()
        report = runner.run(lookback_days=lookback_days)
        return {"success": True, "report": report}
    except Exception as e:
        logger.error(f"回测执行失败: {e}")
        return {"success": False, "error": str(e)}


@router.get("/stats")
async def get_backtest_stats(lookback_days: int = Query(60, ge=7, le=365)):
    """获取回测统计数据（不执行回填，仅查询已有数据）"""
    try:
        from src.backtest import BacktestRunner
        runner = BacktestRunner()
        report = runner._generate_stats_report(lookback_days)
        return {"success": True, "report": report}
    except Exception as e:
        logger.error(f"获取回测统计失败: {e}")
        return {"success": False, "error": str(e)}


@router.get("/records")
async def get_backtest_records(
    code: Optional[str] = Query(None, description="股票代码"),
    limit: int = Query(50, ge=1, le=200),
    lookback_days: int = Query(60, ge=7, le=365),
):
    """获取回测记录明细"""
    try:
        from datetime import datetime, timedelta
        from sqlalchemy import select, and_, desc
        from src.storage import DatabaseManager, AnalysisHistory

        db = DatabaseManager()
        cutoff = datetime.now() - timedelta(days=lookback_days)

        with db.get_session() as session:
            conditions = [
                AnalysisHistory.created_at >= cutoff,
                AnalysisHistory.backtest_filled == 1,
            ]
            if code:
                conditions.append(AnalysisHistory.code == code)

            results = session.execute(
                select(AnalysisHistory)
                .where(and_(*conditions))
                .order_by(desc(AnalysisHistory.created_at))
                .limit(limit)
            ).scalars().all()

            records = []
            for r in results:
                records.append({
                    "id": r.id,
                    "code": r.code,
                    "name": r.name,
                    "score": r.sentiment_score,
                    "advice": r.operation_advice,
                    "actual_pct_5d": r.actual_pct_5d,
                    "hit_stop_loss": bool(r.hit_stop_loss),
                    "hit_take_profit": bool(r.hit_take_profit),
                    "stop_loss": r.stop_loss,
                    "take_profit": r.take_profit,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                })

        return {"success": True, "records": records, "total": len(records)}
    except Exception as e:
        logger.error(f"获取回测记录失败: {e}")
        return {"success": False, "error": str(e)}

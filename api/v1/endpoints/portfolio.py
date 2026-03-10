# -*- coding: utf-8 -*-
"""
持仓管理 & 监控 API
"""

import logging
from datetime import date
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.config import Config
from src.services.portfolio_service import (
    add_portfolio, remove_portfolio, list_portfolio, get_portfolio,
    add_watchlist, remove_watchlist, list_watchlist, update_watchlist_analysis,
    monitor_portfolio,
    add_portfolio_log, list_portfolio_logs, update_portfolio_horizon,
    get_ai_horizon_suggestion, update_next_review_date,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Pydantic 模型 ───────────────────────────

class PortfolioAddRequest(BaseModel):
    code: str
    name: str = ''
    cost_price: float
    shares: int = 0
    entry_date: Optional[date] = None
    notes: str = ''
    holding_horizon_label: Optional[str] = None


class PortfolioLogRequest(BaseModel):
    action: str
    price: Optional[float] = None
    shares: Optional[int] = None
    reason: str = ''
    triggered_by: str = 'manual'


class HorizonUpdateRequest(BaseModel):
    holding_horizon_label: str


class WatchlistAddRequest(BaseModel):
    code: str
    name: str = ''
    notes: str = ''


# ─── 持仓 CRUD ───────────────────────────────

@router.get("/portfolio", summary="获取所有持仓")
def api_list_portfolio():
    from src.services.portfolio_risk_service import calculate_sector_exposure
    items = list_portfolio()
    sector_exposure = None
    try:
        sector_exposure = calculate_sector_exposure(items)
    except Exception:
        pass
    return {"items": items, "sector_exposure": sector_exposure}


@router.post("/portfolio", summary="新增/更新持仓")
def api_add_portfolio(req: PortfolioAddRequest):
    item = add_portfolio(
        code=req.code,
        name=req.name,
        cost_price=req.cost_price,
        shares=req.shares,
        entry_date=req.entry_date,
        notes=req.notes,
        holding_horizon_label=req.holding_horizon_label,
    )
    return {"item": item}


@router.get("/portfolio/{code}/horizon-suggestion", summary="获取 AI 建议的持仓周期")
def api_get_horizon_suggestion(code: str):
    suggestion = get_ai_horizon_suggestion(code)
    return {"suggestion": suggestion}


@router.put("/portfolio/{code}/horizon", summary="更新持仓周期标签")
def api_update_horizon(code: str, req: HorizonUpdateRequest):
    ok = update_portfolio_horizon(code, req.holding_horizon_label)
    if not ok:
        raise HTTPException(status_code=404, detail=f"持仓 {code} 不存在")
    # P5: 同时更新再分析日期
    update_next_review_date(code, req.holding_horizon_label)
    return {"success": True}


@router.post("/portfolio/{code}/refresh-review-date", summary="重新计算再分析日期")
def api_refresh_review_date(code: str):
    review_date = update_next_review_date(code)
    return {"next_review_at": review_date}


@router.delete("/portfolio/{code}", summary="删除持仓")
def api_remove_portfolio(code: str):
    ok = remove_portfolio(code)
    if not ok:
        raise HTTPException(status_code=404, detail=f"持仓 {code} 不存在")
    return {"success": True}


@router.get("/portfolio/{code}/logs", summary="获取单只股票的持仓操作日志")
def api_get_portfolio_logs(code: str, limit: int = Query(20, ge=1, le=200)):
    """获取单只股票的持仓操作日志（按时间倒序）"""
    try:
        logs = list_portfolio_logs(code, limit)
        return {"logs": logs, "count": len(logs)}
    except Exception as e:
        logger.error(f"获取操作日志失败 {code}: {e}")
        return {"logs": [], "count": 0}


@router.get("/portfolio/{code}", summary="获取单只持仓详情")
def api_get_portfolio(code: str):
    item = get_portfolio(code)
    if not item:
        raise HTTPException(status_code=404, detail=f"持仓 {code} 不存在")
    return {"item": item}


# ─── P6: 散户简化视图 ───────────────────────

@router.get("/portfolio/{code}/simple", summary="散户简化视图（大字版信号+一句话建议）")
def api_simple_view(code: str):
    """
    返回最简化的持仓信息，供散户快速决策。
    包含：信号灯颜色、P&L、止损价、一句话操作建议。
    """
    import json as _json
    try:
        holding = get_portfolio(code)
        from src.storage import DatabaseManager, AnalysisHistory
        from sqlalchemy import select, desc as _desc
        db = DatabaseManager.get_instance()
        with db.get_session() as session:
            rec = session.execute(
                select(AnalysisHistory)
                .where(AnalysisHistory.code == code)
                .order_by(_desc(AnalysisHistory.created_at))
                .limit(1)
            ).scalar_one_or_none()

        signal_data = {'signal': 'unknown', 'current_price': None, 'pnl_pct': None, 'atr_stop': None}
        try:
            signals = monitor_portfolio()
            sig = next((s for s in signals if s.get('code') == code), None)
            if sig:
                signal_data = sig
        except Exception:
            pass

        advice_short = ''
        analysis_summary = ''
        score = None
        analyzed_at = None
        if rec:
            advice_short = rec.operation_advice or ''
            score = rec.sentiment_score
            analyzed_at = rec.created_at.isoformat() if rec.created_at else None
            try:
                raw = _json.loads(rec.raw_result or '{}')
                full_summary = raw.get('dashboard', {}).get('analysis_summary') or raw.get('analysis_summary', '')
                analysis_summary = (full_summary[:120] + '…') if len(full_summary) > 120 else full_summary
            except Exception:
                pass

        signal = signal_data.get('signal', 'unknown')
        color_map = {'stop_loss': 'red', 'reduce': 'orange', 'add_watch': 'green', 'hold': 'blue', 'unknown': 'gray'}
        emoji_map = {'stop_loss': '🔴', 'reduce': '🟠', 'add_watch': '🟢', 'hold': '🔵', 'unknown': '⚫'}

        return {
            'code': code,
            'name': holding.get('name', '') if holding else '',
            'signal': signal,
            'signal_color': color_map.get(signal, 'gray'),
            'signal_emoji': emoji_map.get(signal, '⚫'),
            'signal_text': signal_data.get('signal_text', ''),
            'current_price': signal_data.get('current_price') or 0,
            'pnl_pct': signal_data.get('pnl_pct') or 0,
            'atr_stop': signal_data.get('atr_stop') or 0,
            'cost_price': (holding.get('cost_price') if holding else None) or 0,
            'holding_horizon_label': holding.get('holding_horizon_label') if holding else None,
            'next_review_at': holding.get('next_review_at') if holding else None,
            'advice_short': advice_short,
            'analysis_summary': analysis_summary,
            'score': score,
            'analyzed_at': analyzed_at,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── 持仓监控 ────────────────────────────────

@router.get("/portfolio/monitor/signals", summary="获取所有持仓的实时监控信号")
def api_monitor_portfolio():
    """
    遍历持仓列表，获取实时价格、更新ATR追踪止损、生成操作信号。
    前端每2分钟轮询一次。
    """
    try:
        from src.services.portfolio_risk_service import calculate_sector_exposure
        signals = monitor_portfolio()
        _NUMERIC_DEFAULTS = {
            'current_price': 0, 'pnl_pct': 0, 'atr_stop': 0,
            'highest_price': 0, 'stop_pnl_pct': 0, 'shares': 0,
            'cost_price': 0,
        }
        for sig in signals:
            for key, default in _NUMERIC_DEFAULTS.items():
                if sig.get(key) is None:
                    sig[key] = default
        concentration_warnings = _calc_concentration_warnings(signals)
        portfolio_items = list_portfolio()
        sector_exposure = None
        try:
            sector_exposure = calculate_sector_exposure(portfolio_items)
        except Exception:
            pass
        config = Config()
        portfolio_size = config.portfolio_size
        total_market_value = sum(
            (s.get('current_price') or 0) * (s.get('shares') or 0)
            for s in signals
        )
        return {
            "signals": signals,
            "count": len(signals),
            "concentration_warnings": concentration_warnings,
            "sector_exposure": sector_exposure,
            "portfolio_size": portfolio_size,
            "total_market_value": round(total_market_value, 2),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _calc_concentration_warnings(signals: list) -> list:
    """从最近分析记录里读取板块/仓位信息，运行 PortfolioAnalyzer 生成集中度预警"""
    try:
        import json
        from src.storage import DatabaseManager, AnalysisHistory
        from src.analyzer import AnalysisResult
        from src.portfolio_analyzer import PortfolioAnalyzer
        from sqlalchemy import select, desc, and_

        if not signals:
            return []

        db = DatabaseManager.get_instance()
        codes = [s['code'] for s in signals]

        # 取每只股票最近一条分析记录（含 score_breakdown / sector / position_pct）
        fake_results = []
        for sig in signals:
            code = sig['code']
            with db.get_session() as session:
                rec = session.execute(
                    select(AnalysisHistory)
                    .where(AnalysisHistory.code == code)
                    .order_by(desc(AnalysisHistory.created_at))
                    .limit(1)
                ).scalar_one_or_none()

            if not rec:
                continue

            r = AnalysisResult(
                code=code,
                name=sig.get('name', ''),
                sentiment_score=rec.sentiment_score or 50,
                operation_advice=rec.operation_advice or '',
                trend_prediction='',
                analysis_summary='',
                success=True,
            )
            # 根据信号确定 decision_type
            signal_val = sig.get('signal', 'hold')
            r.decision_type = 'sell' if signal_val in ('stop_loss', 'reduce') else 'hold'

            # 从 raw_result 里提取 dashboard 数据（板块、仓位）
            if rec.raw_result:
                try:
                    raw = json.loads(rec.raw_result)
                    db_data = raw.get('dashboard', {})
                    qe = db_data.get('quant_extras', {}) or {}
                    current_price = sig.get('current_price') or 0
                    shares = sig.get('shares') or 0
                    if current_price > 0 and shares > 0:
                        config = Config()
                        total_capital = config.portfolio_size
                        if total_capital <= 0:
                            total_capital = sum(
                                (s.get('current_price') or 0) * (s.get('shares') or 0)
                                for s in signals
                            )
                            logger.warning("portfolio_size 未配置，fallback 到持仓总市值 %.0f 计算集中度", total_capital)
                        if total_capital > 0:
                            pos_pct = round(current_price * shares / total_capital * 100)
                            qe['suggested_position_pct'] = max(pos_pct, qe.get('suggested_position_pct', 0))
                    r.dashboard = {'quant_extras': qe}
                except Exception:
                    pass

            fake_results.append(r)

        if not fake_results:
            return []

        analyzer = PortfolioAnalyzer()
        report = analyzer.analyze(fake_results)
        return report.concentration_warnings or []
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"concentration_warnings 计算失败: {e}")
        return []


# ─── 关注股 CRUD ──────────────────────────────

@router.get("/watchlist", summary="获取所有关注股")
def api_list_watchlist(sort_by: str = Query('score', description="排序方式: score / change / date")):
    return {"items": list_watchlist(sort_by=sort_by)}


@router.post("/watchlist", summary="新增关注股")
def api_add_watchlist(req: WatchlistAddRequest):
    item = add_watchlist(code=req.code, name=req.name, notes=req.notes)
    return {"item": item}


@router.delete("/watchlist/{code}", summary="删除关注股")
def api_remove_watchlist(code: str):
    ok = remove_watchlist(code)
    if not ok:
        raise HTTPException(status_code=404, detail=f"关注股 {code} 不存在")
    return {"success": True}


@router.post("/watchlist/{code}/sync", summary="同步关注股分析结果")
def api_sync_watchlist(code: str, score: int, advice: str = '', summary: str = ''):
    """分析完成后由前端调用，将最新评分写入关注股快照"""
    ok = update_watchlist_analysis(code=code, score=score, advice=advice, summary=summary)
    if not ok:
        raise HTTPException(status_code=404, detail=f"关注股 {code} 不存在，请先加入关注列表")
    return {"success": True}

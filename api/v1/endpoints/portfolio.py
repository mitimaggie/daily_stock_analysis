# -*- coding: utf-8 -*-
"""
持仓管理 & 监控 API
"""

from datetime import date
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.services.portfolio_service import (
    add_portfolio, remove_portfolio, list_portfolio, get_portfolio,
    add_watchlist, remove_watchlist, list_watchlist, update_watchlist_analysis,
    monitor_portfolio,
)

router = APIRouter()


# ─── Pydantic 模型 ───────────────────────────

class PortfolioAddRequest(BaseModel):
    code: str
    name: str = ''
    cost_price: float
    shares: int = 0
    entry_date: Optional[date] = None
    notes: str = ''


class WatchlistAddRequest(BaseModel):
    code: str
    name: str = ''
    notes: str = ''


# ─── 持仓 CRUD ───────────────────────────────

@router.get("/portfolio", summary="获取所有持仓")
def api_list_portfolio():
    return {"items": list_portfolio()}


@router.post("/portfolio", summary="新增/更新持仓")
def api_add_portfolio(req: PortfolioAddRequest):
    item = add_portfolio(
        code=req.code,
        name=req.name,
        cost_price=req.cost_price,
        shares=req.shares,
        entry_date=req.entry_date,
        notes=req.notes,
    )
    return {"item": item}


@router.delete("/portfolio/{code}", summary="删除持仓")
def api_remove_portfolio(code: str):
    ok = remove_portfolio(code)
    if not ok:
        raise HTTPException(status_code=404, detail=f"持仓 {code} 不存在")
    return {"success": True}


@router.get("/portfolio/{code}", summary="获取单只持仓详情")
def api_get_portfolio(code: str):
    item = get_portfolio(code)
    if not item:
        raise HTTPException(status_code=404, detail=f"持仓 {code} 不存在")
    return {"item": item}


# ─── 持仓监控 ────────────────────────────────

@router.get("/portfolio/monitor/signals", summary="获取所有持仓的实时监控信号")
def api_monitor_portfolio():
    """
    遍历持仓列表，获取实时价格、更新ATR追踪止损、生成操作信号。
    前端每2分钟轮询一次。
    """
    try:
        signals = monitor_portfolio()
        return {"signals": signals, "count": len(signals)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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

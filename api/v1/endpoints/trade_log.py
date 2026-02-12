# -*- coding: utf-8 -*-
"""
交易日志接口 (P2)

提供交易记录的 CRUD 操作：
- POST /api/v1/trade-log/ 创建交易记录
- GET /api/v1/trade-log/ 获取交易记录列表
- GET /api/v1/trade-log/stats 获取交易统计
- DELETE /api/v1/trade-log/{log_id} 删除交易记录

存储：JSON 文件（轻量级，无需数据库）
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()

# 存储路径
TRADE_LOG_DIR = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data')
TRADE_LOG_FILE = os.path.join(TRADE_LOG_DIR, 'trade_log.json')


# ============ Schema ============

class TradeLogCreate(BaseModel):
    """创建交易记录"""
    stock_code: str = Field(..., description="股票代码")
    stock_name: str = Field("", description="股票名称")
    action: str = Field(..., description="操作类型: buy/sell/hold/watch")
    price: float = Field(0, description="操作价格")
    shares: int = Field(0, description="操作股数")
    amount: float = Field(0, description="操作金额")
    reason: str = Field("", description="操作理由")
    analysis_score: Optional[int] = Field(None, description="当时的分析评分")
    analysis_advice: str = Field("", description="当时的分析建议")
    query_id: str = Field("", description="关联的分析 queryId")
    note: str = Field("", description="备注")


class TradeLogItem(TradeLogCreate):
    """交易记录（含ID和时间）"""
    id: str = Field(..., description="记录ID")
    created_at: str = Field(..., description="创建时间")
    # 事后回顾字段
    review_result: str = Field("", description="事后结果: profit/loss/flat")
    review_pnl: float = Field(0, description="盈亏金额")
    review_pnl_pct: float = Field(0, description="盈亏百分比")
    review_note: str = Field("", description="事后复盘备注")
    reviewed_at: str = Field("", description="复盘时间")


class TradeLogStats(BaseModel):
    """交易统计"""
    total_trades: int = 0
    buy_count: int = 0
    sell_count: int = 0
    reviewed_count: int = 0
    profit_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_pnl_pct: float = 0.0
    followed_advice_count: int = 0  # 跟随分析建议的次数


class TradeLogReview(BaseModel):
    """事后复盘"""
    review_result: str = Field(..., description="结果: profit/loss/flat")
    review_pnl: float = Field(0, description="盈亏金额")
    review_pnl_pct: float = Field(0, description="盈亏百分比")
    review_note: str = Field("", description="复盘备注")


# ============ Storage ============

def _load_logs() -> List[dict]:
    """加载交易日志"""
    if not os.path.exists(TRADE_LOG_FILE):
        return []
    try:
        with open(TRADE_LOG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_logs(logs: List[dict]):
    """保存交易日志"""
    os.makedirs(TRADE_LOG_DIR, exist_ok=True)
    with open(TRADE_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


# ============ Endpoints ============

@router.post("/", response_model=TradeLogItem)
async def create_trade_log(req: TradeLogCreate):
    """创建交易记录"""
    logs = _load_logs()
    item = req.model_dump()
    item['id'] = str(uuid.uuid4())[:8]
    item['created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    item['review_result'] = ""
    item['review_pnl'] = 0
    item['review_pnl_pct'] = 0
    item['review_note'] = ""
    item['reviewed_at'] = ""
    logs.insert(0, item)  # 最新的在前
    _save_logs(logs)
    logger.info(f"[交易日志] 新增: {item['stock_code']} {item['action']} @ {item['price']}")
    return item


@router.get("/", response_model=List[TradeLogItem])
async def list_trade_logs(
    stock_code: Optional[str] = Query(None, description="按股票代码筛选"),
    action: Optional[str] = Query(None, description="按操作类型筛选"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """获取交易记录列表"""
    logs = _load_logs()
    if stock_code:
        logs = [l for l in logs if l.get('stock_code') == stock_code]
    if action:
        logs = [l for l in logs if l.get('action') == action]
    return logs[offset:offset + limit]


@router.get("/stats", response_model=TradeLogStats)
async def get_trade_stats(
    stock_code: Optional[str] = Query(None, description="按股票代码筛选"),
):
    """获取交易统计"""
    logs = _load_logs()
    if stock_code:
        logs = [l for l in logs if l.get('stock_code') == stock_code]

    stats = TradeLogStats()
    stats.total_trades = len(logs)
    stats.buy_count = sum(1 for l in logs if l.get('action') == 'buy')
    stats.sell_count = sum(1 for l in logs if l.get('action') == 'sell')

    reviewed = [l for l in logs if l.get('review_result')]
    stats.reviewed_count = len(reviewed)
    stats.profit_count = sum(1 for l in reviewed if l.get('review_result') == 'profit')
    stats.loss_count = sum(1 for l in reviewed if l.get('review_result') == 'loss')

    if stats.reviewed_count > 0:
        stats.win_rate = round(stats.profit_count / stats.reviewed_count * 100, 1)
        stats.total_pnl = round(sum(l.get('review_pnl', 0) for l in reviewed), 2)
        pnl_pcts = [l.get('review_pnl_pct', 0) for l in reviewed if l.get('review_pnl_pct', 0) != 0]
        stats.avg_pnl_pct = round(sum(pnl_pcts) / len(pnl_pcts), 2) if pnl_pcts else 0

    # 统计跟随分析建议的次数
    for l in logs:
        advice = l.get('analysis_advice', '')
        action_type = l.get('action', '')
        if advice and action_type:
            if ('买' in advice and action_type == 'buy') or \
               ('卖' in advice and action_type == 'sell') or \
               ('观望' in advice and action_type in ('hold', 'watch')):
                stats.followed_advice_count += 1

    return stats


@router.put("/{log_id}/review", response_model=TradeLogItem)
async def review_trade_log(log_id: str, review: TradeLogReview):
    """事后复盘：更新交易记录的结果"""
    logs = _load_logs()
    for log in logs:
        if log.get('id') == log_id:
            log['review_result'] = review.review_result
            log['review_pnl'] = review.review_pnl
            log['review_pnl_pct'] = review.review_pnl_pct
            log['review_note'] = review.review_note
            log['reviewed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            _save_logs(logs)
            return log
    raise HTTPException(status_code=404, detail=f"交易记录 {log_id} 不存在")


@router.delete("/{log_id}")
async def delete_trade_log(log_id: str):
    """删除交易记录"""
    logs = _load_logs()
    new_logs = [l for l in logs if l.get('id') != log_id]
    if len(new_logs) == len(logs):
        raise HTTPException(status_code=404, detail=f"交易记录 {log_id} 不存在")
    _save_logs(new_logs)
    return {"message": "已删除", "id": log_id}

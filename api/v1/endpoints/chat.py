# -*- coding: utf-8 -*-
"""
===================================
AI 对话接口
===================================

职责：
1. 提供 POST /api/v1/chat 对话接口
2. 基于分析报告上下文与用户对话
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from api.deps import get_database_manager
from src.storage import DatabaseManager
from src.services.history_service import HistoryService
from src.services.chat_service import get_chat_service

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatMessage(BaseModel):
    role: str = Field(..., description="消息角色: user / assistant")
    content: str = Field(..., description="消息内容")


class ChatRequest(BaseModel):
    query_id: str = Field(..., description="关联的分析报告 query_id")
    messages: List[ChatMessage] = Field(..., description="对话历史（含当前用户消息）")


class ChatResponse(BaseModel):
    reply: str = Field(..., description="AI 回复内容")


@router.post(
    "",
    response_model=ChatResponse,
    summary="AI 对话",
    description="基于分析报告上下文与 AI 深入探讨",
)
def chat(
    req: ChatRequest,
    db_manager: DatabaseManager = Depends(get_database_manager),
):
    """AI 对话端点"""
    svc = get_chat_service()
    if not svc.is_available():
        raise HTTPException(status_code=503, detail="AI 服务未配置")

    # 获取报告数据
    history_svc = HistoryService(db_manager)
    report = history_svc.get_history_detail(req.query_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"报告 {req.query_id} 不存在")

    # 构建上下文
    report_context = svc.build_report_context(report)

    # 对话
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    reply = svc.chat(messages, report_context)

    return ChatResponse(reply=reply)

# -*- coding: utf-8 -*-
"""
===================================
AI 对话接口
===================================

职责：
1. 提供 POST /api/v1/chat 对话接口
2. 提供 POST /api/v1/chat/stream 流式对话接口
3. 基于分析报告上下文与用户对话
"""

import json
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
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
    strategy_id: Optional[str] = Field(None, description="策略模式 ID（可选，如 trend_momentum/value_rebound/risk_check 等）")


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
    reply = svc.chat(messages, report_context, strategy_id=req.strategy_id)

    return ChatResponse(reply=reply)


@router.post(
    "/stream",
    summary="AI 流式对话",
    description="基于分析报告上下文，流式返回 AI 回复（SSE）。支持 Agent 工具调用进度事件。",
)
def chat_stream(
    req: ChatRequest,
    db_manager: DatabaseManager = Depends(get_database_manager),
):
    """流式对话端点 — SSE 格式

    SSE 事件格式（每行 data: <json>）：
    - {"type": "thinking"}                                    — AI 正在思考
    - {"type": "tool_start", "tool": ..., "display_name": ...} — 工具调用开始
    - {"type": "tool_done",  "tool": ..., "display_name": ...} — 工具调用完成
    - {"type": "chunk", "text": ...}                          — 回复文本片段
    - {"type": "done"}                                        — 完成
    - {"type": "error", "message": ...}                       — 错误

    兼容旧格式：旧客户端可通过 payload.chunk / payload.done / payload.error 读取
    """
    svc = get_chat_service()
    if not svc.is_available() and not svc.is_agent_available():
        raise HTTPException(status_code=503, detail="AI 服务未配置")

    history_svc = HistoryService(db_manager)
    report = history_svc.get_history_detail(req.query_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"报告 {req.query_id} 不存在")

    report_context = svc.build_report_context(report)
    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    def event_generator():
        try:
            for event in svc.chat_stream(messages, report_context, query_id=req.query_id, strategy_id=req.strategy_id):
                event_type = event.get("type", "")
                if event_type == "chunk":
                    # 兼容旧格式：同时发送 chunk 字段
                    payload = {**event, "chunk": event.get("text", "")}
                elif event_type == "done":
                    # 兼容旧格式：同时发送 done 字段
                    payload = {**event, "done": True}
                elif event_type == "error":
                    # 兼容旧格式：同时发送 error 字段
                    payload = {**event, "error": event.get("message", "")}
                else:
                    payload = event
                data = json.dumps(payload, ensure_ascii=False)
                yield f"data: {data}\n\n"
        except Exception as e:
            logger.error(f"Chat stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e), 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/strategies",
    summary="获取可用策略列表",
    description="返回所有可选的 Agent 分析策略（id, name, description）",
)
def list_strategies():
    """Agent 策略列表接口"""
    try:
        from src.agent.strategy_manager import list_strategies as _list
        return {"strategies": _list()}
    except Exception as e:
        logger.warning(f"list_strategies 失败: {e}")
        return {"strategies": []}

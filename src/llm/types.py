# -*- coding: utf-8 -*-
"""
LLM 调用相关的通用类型定义

职责：
1. LLMResponse — 统一的 LLM 调用结果数据类
2. CallMode — LLM 调用模式枚举
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class CallMode(Enum):
    """LLM 调用模式"""
    TEXT = "text"
    JSON_MODE = "json_mode"
    FUNCTION_CALLING = "function_calling"
    STREAM = "stream"


@dataclass
class LLMResponse:
    """LLM 调用统一结果

    Attributes:
        text: 模型输出文本
        json_data: JSON Mode 下解析后的 dict（纯文本模式为 None）
        model_used: 实际使用的模型名（含 fallback 信息）
        input_tokens: 输入 token 数
        output_tokens: 输出 token 数
        latency_ms: 端到端延迟（毫秒）
        success: 调用是否成功
        error: 失败时的错误信息
    """
    text: str = ""
    json_data: Optional[Dict[str, Any]] = None
    model_used: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    success: bool = True
    error: Optional[str] = None

# -*- coding: utf-8 -*-
"""
Token 计费追踪器

职责：
1. 按 scene × model 分桶记录每次 LLM 调用的 token 消耗
2. 估算费用（基于 Gemini / OpenAI 公开定价）
3. 线程安全，单例模式，整个进程共享一个实例
"""

import logging
import threading
from collections import defaultdict
from typing import Any, Dict

logger = logging.getLogger(__name__)

# 费率表（美元 / 百万 token）
_PRICE_TABLE: Dict[str, Dict[str, float]] = {
    "pro": {"input": 1.25, "output": 10.0},
    "flash": {"input": 0.10, "output": 0.40},
    "openai": {"input": 0.15, "output": 0.60},
}

# 模型名到费率 key 的映射关键词
_MODEL_TIER_KEYWORDS = {
    "pro": "pro",
    "flash": "flash",
    "gpt": "openai",
    "openai": "openai",
}


def _resolve_tier(model: str) -> str:
    """根据模型名推断费率档位"""
    model_lower = model.lower()
    for keyword, tier in _MODEL_TIER_KEYWORDS.items():
        if keyword in model_lower:
            return tier
    return "pro"


class TokenTracker:
    """线程安全的 Token 计费追踪器（单例）"""

    _instance: "TokenTracker | None" = None
    _lock_cls = threading.Lock()

    def __new__(cls) -> "TokenTracker":
        with cls._lock_cls:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._lock = threading.Lock()
                inst._buckets: Dict[str, Dict[str, Any]] = defaultdict(
                    lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0}
                )
                cls._instance = inst
            return cls._instance

    @classmethod
    def get_instance(cls) -> "TokenTracker":
        return cls()

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（仅用于测试）"""
        with cls._lock_cls:
            cls._instance = None

    def record(
        self, scene: str, model: str, input_tokens: int, output_tokens: int
    ) -> None:
        """记录一次 LLM 调用"""
        key = f"{scene}|{model}"
        with self._lock:
            bucket = self._buckets[key]
            bucket["calls"] += 1
            bucket["input_tokens"] += input_tokens
            bucket["output_tokens"] += output_tokens

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """估算单条记录费用（美元）"""
        tier = _resolve_tier(model)
        prices = _PRICE_TABLE.get(tier, _PRICE_TABLE["pro"])
        return (
            input_tokens * prices["input"] / 1_000_000
            + output_tokens * prices["output"] / 1_000_000
        )

    def get_summary(self) -> Dict[str, Any]:
        """按 scene × model 分桶返回统计"""
        with self._lock:
            result: Dict[str, Any] = {}
            for key, bucket in self._buckets.items():
                scene, model = key.split("|", 1)
                cost = self._estimate_cost(
                    model, bucket["input_tokens"], bucket["output_tokens"]
                )
                result[key] = {
                    "scene": scene,
                    "model": model,
                    "calls": bucket["calls"],
                    "input_tokens": bucket["input_tokens"],
                    "output_tokens": bucket["output_tokens"],
                    "estimated_cost_usd": round(cost, 6),
                }
            return result

    def get_session_total(self) -> Dict[str, Any]:
        """返回本次会话的总计"""
        summary = self.get_summary()
        total_calls = 0
        total_input = 0
        total_output = 0
        total_cost = 0.0
        for entry in summary.values():
            total_calls += entry["calls"]
            total_input += entry["input_tokens"]
            total_output += entry["output_tokens"]
            total_cost += entry["estimated_cost_usd"]
        return {
            "total_calls": total_calls,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_estimated_cost_usd": round(total_cost, 6),
        }

    def log_summary(self) -> None:
        """用 logger.info 输出当前统计"""
        total = self.get_session_total()
        if total["total_calls"] == 0:
            return
        logger.info(
            "[TokenTracker] 会话累计: %d 次调用, 输入 %d tokens, 输出 %d tokens, 估算费用 $%.4f",
            total["total_calls"],
            total["total_input_tokens"],
            total["total_output_tokens"],
            total["total_estimated_cost_usd"],
        )
        for key, entry in self.get_summary().items():
            logger.info(
                "  ├ %s: %d 次, in=%d out=%d $%.4f",
                key,
                entry["calls"],
                entry["input_tokens"],
                entry["output_tokens"],
                entry["estimated_cost_usd"],
            )

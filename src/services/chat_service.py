# -*- coding: utf-8 -*-
"""
===================================
AI 对话服务
===================================

职责：
1. 基于分析报告上下文与用户对话
2. 复用现有 Gemini/OpenAI API 配置
3. 支持流式响应（SSE）
"""

import json
import logging
from typing import Optional, Dict, Any, List, AsyncIterator

from src.config import get_config

logger = logging.getLogger(__name__)


class ChatService:
    """AI 对话服务（Phase 1: 纯 prompt + 报告上下文）"""

    SYSTEM_PROMPT = """你是一位专业的A股投资分析助手。用户正在查看一份股票分析报告，你需要基于报告内容与用户深入探讨。

## 你的职责
1. **解读报告**：用通俗语言解释技术指标、量化结论、风险提示的含义
2. **回答疑问**：回答用户关于该股票分析结论的任何问题
3. **假设推演**：帮用户分析"如果价格到达某个位置"等假设场景
4. **策略建议**：结合用户持仓情况，给出个性化的操作建议

## 重要约束
- 所有分析必须基于报告中的数据，**禁止编造不存在的数据**
- 量化评分和技术指标由模型计算，你不可修改，但可以解释
- 如果用户问到报告中没有的信息，明确说明"报告中未包含此数据"
- 每次回答结尾注明：数据截止时间为报告生成时间，不代表实时行情
- 使用简洁专业的中文回答，避免冗长

## 免责声明
你提供的是分析参考，不构成投资建议。投资有风险，决策需谨慎。
"""

    def __init__(self):
        self._model = None
        self._model_fallback = None
        self._openai_client = None
        self._use_openai = False
        self._initialized = False

    def _ensure_init(self):
        """延迟初始化 AI 模型"""
        if self._initialized:
            return
        self._initialized = True

        config = get_config()
        api_key = config.gemini_api_key

        if api_key and "your_" not in api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                self._model = genai.GenerativeModel(model_name=config.gemini_model)
                fb = getattr(config, "gemini_model_fallback", None)
                if fb and str(fb).strip() and str(fb).strip() != config.gemini_model:
                    self._model_fallback = genai.GenerativeModel(model_name=str(fb).strip())
            except Exception as e:
                logger.warning(f"Chat: Gemini 初始化失败: {e}")

        if not self._model and config.openai_api_key:
            try:
                from openai import OpenAI
                self._openai_client = OpenAI(
                    api_key=config.openai_api_key,
                    base_url=config.openai_base_url,
                )
                self._use_openai = True
            except Exception as e:
                logger.warning(f"Chat: OpenAI 初始化失败: {e}")

    def is_available(self) -> bool:
        self._ensure_init()
        return self._model is not None or self._openai_client is not None

    def build_report_context(self, report_data: Dict[str, Any]) -> str:
        """从报告数据构建上下文摘要（注入 system prompt）"""
        parts: List[str] = []

        meta = report_data.get("meta") or {}
        summary = report_data.get("summary") or {}
        strategy = report_data.get("strategy") or {}
        details = report_data.get("details") or {}

        # 基本信息
        parts.append(f"股票: {meta.get('stock_name', '未知')} ({meta.get('stock_code', '')})")
        parts.append(f"报告时间: {meta.get('created_at', '未知')}")
        if meta.get("current_price"):
            parts.append(f"当时价格: {meta['current_price']}")

        # 核心结论
        parts.append(f"\n## 核心结论")
        parts.append(f"评分: {summary.get('sentiment_score', 'N/A')}/100 ({summary.get('sentiment_label', '')})")
        parts.append(f"操作建议: {summary.get('operation_advice', 'N/A')}")
        parts.append(f"趋势预测: {summary.get('trend_prediction', 'N/A')}")
        if summary.get("analysis_summary"):
            parts.append(f"分析摘要: {summary['analysis_summary']}")

        # 空仓/持仓建议
        pos_adv = summary.get("position_advice") or {}
        if pos_adv.get("no_position"):
            parts.append(f"空仓建议: {pos_adv['no_position']}")
        if pos_adv.get("has_position"):
            parts.append(f"持仓建议: {pos_adv['has_position']}")

        # 策略点位
        parts.append(f"\n## 策略点位")
        if strategy.get("ideal_buy"):
            parts.append(f"理想买入: {strategy['ideal_buy']}")
        if strategy.get("stop_loss"):
            parts.append(f"止损: {strategy['stop_loss']}")
        if strategy.get("take_profit"):
            parts.append(f"短线止盈: {strategy['take_profit']}")

        hs = strategy.get("holding_strategy") or {}
        if hs:
            parts.append(f"\n## 持仓者策略")
            if hs.get("recommended_stop"):
                parts.append(f"推荐止损: {hs['recommended_stop']} ({hs.get('recommended_stop_type', '')})")
            if hs.get("recommended_stop_reason"):
                parts.append(f"推荐理由: {hs['recommended_stop_reason']}")
            if hs.get("recommended_target"):
                parts.append(f"推荐止盈: {hs['recommended_target']} ({hs.get('recommended_target_type', '')})")
            if hs.get("advice"):
                parts.append(f"综合建议: {hs['advice']}")
            # 全部锚点
            anchors = []
            for k, label in [("trailing_stop", "移动止盈"), ("stop_loss_short", "短线止损"),
                             ("stop_loss_mid", "中线止损"), ("target_short", "短线目标"),
                             ("target_mid", "中线目标")]:
                if hs.get(k):
                    anchors.append(f"{label}={hs[k]}")
            if anchors:
                parts.append(f"全部锚点: {', '.join(anchors)}")

        # 量化指标摘要（从 raw_result 提取关键信息）
        raw = details.get("raw_result") or {}
        dashboard = raw.get("dashboard") or {} if isinstance(raw, dict) else {}
        qe = dashboard.get("quant_extras") or {}
        if qe:
            parts.append(f"\n## 量化指标")
            key_fields = [
                ("trend_status", "趋势"), ("buy_signal", "信号"),
                ("macd_status", "MACD"), ("kdj_status", "KDJ"), ("rsi_status", "RSI"),
                ("volume_status", "量能"), ("trend_strength", "趋势强度"),
                ("risk_reward_ratio", "风险收益比"), ("risk_reward_verdict", "R:R判断"),
                ("take_profit_plan", "分批止盈方案"),
            ]
            for key, label in key_fields:
                val = qe.get(key)
                if val:
                    parts.append(f"{label}: {val}")

        # 情报面
        intel = dashboard.get("intelligence") or {}
        if intel.get("risk_alerts"):
            parts.append(f"\n## 风险提示")
            for alert in intel["risk_alerts"][:5]:
                parts.append(f"- {alert}")
        if intel.get("positive_catalysts"):
            parts.append(f"\n## 利好因素")
            for cat in intel["positive_catalysts"][:5]:
                parts.append(f"- {cat}")

        return "\n".join(parts)

    def chat(
        self,
        messages: List[Dict[str, str]],
        report_context: str,
    ) -> str:
        """同步对话（非流式）

        Args:
            messages: 对话历史 [{"role": "user"/"assistant", "content": "..."}]
            report_context: 报告上下文文本

        Returns:
            AI 回复文本
        """
        self._ensure_init()
        if not self.is_available():
            return "AI 服务未配置，请检查 GEMINI_API_KEY 或 OPENAI_API_KEY 环境变量。"

        config = get_config()
        temperature = getattr(config, "gemini_temperature", 0.3)
        timeout = getattr(config, "gemini_request_timeout", 60)

        full_system = f"{self.SYSTEM_PROMPT}\n\n## 当前报告数据\n{report_context}"

        if self._use_openai and self._openai_client:
            return self._chat_openai(full_system, messages, config, timeout)

        return self._chat_gemini(full_system, messages, temperature, timeout)

    def _chat_gemini(
        self, system: str, messages: List[Dict[str, str]],
        temperature: float, timeout: int,
    ) -> str:
        """Gemini 对话"""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

        # 构建 Gemini 格式的对话
        # Gemini contents 格式: [{"role": "user"/"model", "parts": [{"text": "..."}]}]
        contents = []
        # 把 system prompt + report 作为第一条 user 消息的前缀
        for i, msg in enumerate(messages):
            role = "model" if msg["role"] == "assistant" else "user"
            text = msg["content"]
            if i == 0 and role == "user":
                text = f"[系统指令]\n{system}\n\n[用户问题]\n{text}"
            contents.append({"role": role, "parts": [{"text": text}]})

        gen_cfg = {"temperature": temperature}
        models = [self._model]
        if self._model_fallback:
            models.append(self._model_fallback)

        last_err = None
        for model in models:
            try:
                with ThreadPoolExecutor(max_workers=1) as tp:
                    future = tp.submit(
                        model.generate_content,
                        contents,
                        generation_config=gen_cfg,
                    )
                    resp = future.result(timeout=timeout)
                    return resp.text
            except FuturesTimeout:
                last_err = TimeoutError(f"Gemini 请求超时 ({timeout}s)")
            except Exception as e:
                last_err = e
                logger.warning(f"Chat Gemini 失败: {e}")

        return f"AI 回复失败: {last_err}"

    def _chat_openai(
        self, system: str, messages: List[Dict[str, str]],
        config: Any, timeout: int,
    ) -> str:
        """OpenAI 对话"""
        oai_messages = [{"role": "system", "content": system}]
        for msg in messages:
            oai_messages.append({"role": msg["role"], "content": msg["content"]})

        try:
            r = self._openai_client.chat.completions.create(
                model=config.openai_model,
                messages=oai_messages,
                temperature=getattr(config, "openai_temperature", 0.3),
                timeout=timeout,
            )
            return r.choices[0].message.content
        except Exception as e:
            logger.error(f"Chat OpenAI 失败: {e}")
            return f"AI 回复失败: {e}"


# 单例
_chat_service: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service

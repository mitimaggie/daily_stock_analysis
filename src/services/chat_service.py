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
from typing import Optional, Dict, Any, List, Iterator

from src.config import get_config

logger = logging.getLogger(__name__)


class ChatService:
    """AI 对话服务（Agent 模式：支持 function calling 主动获取数据）"""

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
        self._agent_executor = None
        self._agent_initialized = False

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

    def _ensure_agent_init(self):
        """延迟初始化 Agent 执行引擎"""
        if self._agent_initialized:
            return
        self._agent_initialized = True
        try:
            from src.agent.executor import AgentExecutor
            config = get_config()
            self._agent_executor = AgentExecutor(config)
        except Exception as e:
            logger.warning(f"Chat: Agent 初始化失败: {e}")

    def is_available(self) -> bool:
        self._ensure_init()
        return self._model is not None or self._openai_client is not None

    def is_agent_available(self) -> bool:
        """检查 Agent 模式是否可用"""
        self._ensure_agent_init()
        return self._agent_executor is not None and self._agent_executor.is_available()

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

        # ---- 量化 vs AI 对比 ----
        qva = summary.get("quant_vs_ai") or {}
        if qva:
            parts.append(f"\n## 量化 vs AI 对比")
            if qva.get("quant_score") is not None:
                parts.append(f"量化评分: {qva['quant_score']}/100")
            if qva.get("quant_advice"):
                parts.append(f"量化建议: {qva['quant_advice']}")
            if qva.get("llm_score") is not None:
                parts.append(f"AI评分: {qva['llm_score']}/100")
            if qva.get("llm_advice"):
                parts.append(f"AI建议: {qva['llm_advice']}")
            if qva.get("divergence"):
                parts.append(f"分歧: {qva['divergence']}")
            if qva.get("llm_reasoning"):
                parts.append(f"AI推理: {qva['llm_reasoning']}")

        # ---- 当日行情快照 ----
        today_snap = report_data.get("today_snapshot") or {}
        if today_snap:
            parts.append(f"\n## 当日行情快照")
            for k, label in [("open", "开盘"), ("high", "最高"), ("low", "最低"),
                              ("close", "收盘"), ("volume", "成交量"), ("amount", "成交额"),
                              ("change_pct", "涨跌幅%"), ("amplitude", "振幅%"),
                              ("turnover_rate", "换手率%"), ("volume_ratio", "量比")]:
                val = today_snap.get(k)
                if val is not None:
                    parts.append(f"{label}: {val}")

        # ---- 盘中关键价位 ----
        kpl = strategy.get("key_price_levels") or []
        if kpl:
            parts.append(f"\n## 盘中关键价位")
            for lv in kpl:
                if isinstance(lv, dict):
                    price = lv.get("price", "?")
                    ltype = lv.get("type", "")
                    action = lv.get("action", "")
                    parts.append(f"- {price} ({ltype}) → {action}")

        # ---- 量化指标摘要 ----
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
                ("valuation_verdict", "估值"), ("capital_flow_signal", "资金面"),
                ("chip_signal", "筹码"), ("ma_alignment", "均线排列"),
            ]
            for key, label in key_fields:
                val = qe.get(key)
                if val:
                    parts.append(f"{label}: {val}")

            # 风险因子
            risk_factors = qe.get("risk_factors") or []
            if risk_factors:
                parts.append(f"\n## 量化风险因子")
                for rf in risk_factors[:8]:
                    parts.append(f"- {rf}")

            # 信号共振
            resonance = qe.get("resonance_signals") or []
            if resonance:
                parts.append(f"信号共振({len(resonance)}项): {', '.join(resonance)}")

        # ---- 情报面 ----
        intel = dashboard.get("intelligence") or {}
        if intel.get("sentiment_summary"):
            parts.append(f"\n## 市场情绪")
            parts.append(intel["sentiment_summary"])
        if intel.get("earnings_outlook"):
            parts.append(f"\n## 盈利展望")
            parts.append(intel["earnings_outlook"])
        if intel.get("risk_alerts"):
            parts.append(f"\n## 风险提示")
            for alert in intel["risk_alerts"][:5]:
                parts.append(f"- {alert}")
        if intel.get("positive_catalysts"):
            parts.append(f"\n## 利好因素")
            for cat in intel["positive_catalysts"][:5]:
                parts.append(f"- {cat}")

        # 反面论据
        counter = dashboard.get("counter_arguments") or []
        if counter:
            parts.append(f"\n## 反面论据")
            for ca in counter[:5]:
                parts.append(f"- {ca}")

        # ---- K线形态 ----
        candle_patterns = qe.get("candle_patterns") or [] if qe else []
        candle_summary = qe.get("candle_pattern_summary", "") if qe else ""
        if candle_patterns or candle_summary:
            parts.append(f"\n## K线形态")
            if candle_summary:
                parts.append(f"形态摘要: {candle_summary}")
            for cp in candle_patterns[:5]:
                if isinstance(cp, dict):
                    parts.append(f"- {cp.get('name', '')}: {cp.get('description', '')} (强度{cp.get('strength', 0)}, {cp.get('direction', '')})")

        # ---- 评分趋势 ----
        score_trend = raw.get("score_trend") or {} if isinstance(raw, dict) else {}
        if not score_trend:
            # 也可能在 dashboard 层
            score_trend = dashboard.get("score_trend") or {}
        if score_trend and score_trend.get("scores"):
            parts.append(f"\n## 评分趋势")
            if score_trend.get("summary"):
                parts.append(score_trend["summary"])
            if score_trend.get("inflection"):
                parts.append(f"⚡拐点: {score_trend['inflection']}")
            if score_trend.get("trend_direction"):
                dir_map = {"improving": "改善中", "declining": "恶化中", "stable": "平稳"}
                parts.append(f"趋势方向: {dir_map.get(score_trend['trend_direction'], score_trend['trend_direction'])}")
            # 显示近几次评分
            score_list = score_trend.get("scores", [])[-5:]
            if score_list:
                scores_str = " → ".join(f"{s.get('date','')[-5:]}:{s.get('score','')}分" for s in score_list)
                parts.append(f"历史评分: {scores_str}")

        # ---- 分时数据 ----
        intraday = raw.get("intraday_analysis") or {} if isinstance(raw, dict) else {}
        if not intraday:
            intraday = dashboard.get("intraday_analysis") or {}
        if intraday and intraday.get("available"):
            parts.append(f"\n## 分时分析 ({intraday.get('period', '5min')})")
            if intraday.get("summary"):
                parts.append(intraday["summary"])
            if intraday.get("intraday_vwap"):
                parts.append(f"分时VWAP: {intraday['intraday_vwap']}")
            if intraday.get("momentum"):
                parts.append(f"动能: {intraday['momentum']}")

        return "\n".join(parts)

    def chat(
        self,
        messages: List[Dict[str, str]],
        report_context: str,
        query_id: Optional[str] = None,
        progress_callback=None,
    ) -> str:
        """同步对话（优先使用 Agent function calling 模式）

        Args:
            messages: 对话历史 [{"role": "user"/"assistant", "content": "..."}]
            report_context: 报告上下文文本（Agent 模式下作为初始上下文注入）
            query_id: 关联的报告 ID（可选，Agent 可主动调用 get_analysis_context）
            progress_callback: 工具调用进度回调（可选）

        Returns:
            AI 回复文本
        """
        # 优先尝试 Agent 模式
        if self.is_agent_available():
            try:
                user_message = messages[-1]["content"] if messages else ""
                history = messages[:-1] if len(messages) > 1 else []
                context = {"report_context": report_context}
                if query_id:
                    context["query_id"] = query_id
                result = self._agent_executor.chat(
                    message=user_message,
                    history=history,
                    progress_callback=progress_callback,
                    context=context,
                )
                if result.success:
                    return result.content
                logger.warning(f"Agent chat failed: {result.error}, falling back to plain prompt")
            except Exception as e:
                logger.warning(f"Agent chat exception: {e}, falling back to plain prompt")

        # 回退：纯 prompt 模式
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

    def _build_gemini_contents(
        self, system: str, messages: List[Dict[str, str]],
    ) -> List[Dict]:
        """构建 Gemini 格式的对话内容"""
        contents = []
        for i, msg in enumerate(messages):
            role = "model" if msg["role"] == "assistant" else "user"
            text = msg["content"]
            if i == 0 and role == "user":
                text = f"[系统指令]\n{system}\n\n[用户问题]\n{text}"
            contents.append({"role": role, "parts": [{"text": text}]})
        return contents

    def _chat_gemini(
        self, system: str, messages: List[Dict[str, str]],
        temperature: float, timeout: int,
    ) -> str:
        """Gemini 对话"""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

        contents = self._build_gemini_contents(system, messages)
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

    # ============ 流式对话 ============

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        report_context: str,
        query_id: Optional[str] = None,
    ) -> Iterator[Dict]:
        """流式对话，产出事件字典序列。

        事件类型：
        - {"type": "thinking"}                          — AI 正在思考
        - {"type": "tool_start", "tool": ..., "display_name": ...}  — 工具调用开始
        - {"type": "tool_done",  "tool": ..., "display_name": ...}  — 工具调用完成
        - {"type": "chunk",  "text": ...}               — 最终回复文本片段
        - {"type": "done"}                              — 完成
        - {"type": "error", "message": ...}             — 错误
        """
        # 优先尝试 Agent 模式（同步执行，通过 callback 收集进度事件）
        if self.is_agent_available():
            import queue
            import threading

            event_queue: queue.Queue = queue.Queue()

            def progress_callback(event: Dict):
                event_queue.put(event)

            def run_agent():
                try:
                    user_message = messages[-1]["content"] if messages else ""
                    history = messages[:-1] if len(messages) > 1 else []
                    context = {"report_context": report_context}
                    if query_id:
                        context["query_id"] = query_id
                    result = self._agent_executor.chat(
                        message=user_message,
                        history=history,
                        progress_callback=progress_callback,
                        context=context,
                    )
                    if result.success:
                        event_queue.put({"type": "final", "content": result.content})
                    else:
                        event_queue.put({"type": "agent_error", "error": result.error})
                except Exception as e:
                    event_queue.put({"type": "agent_error", "error": str(e)})

            t = threading.Thread(target=run_agent, daemon=True)
            t.start()

            # 从队列中读取事件，转发给调用方
            while True:
                try:
                    event = event_queue.get(timeout=120)
                except queue.Empty:
                    yield {"type": "error", "message": "Agent 超时"}
                    return

                if event["type"] == "final":
                    # 将最终文本拆成 chunks 逐字输出
                    content = event["content"]
                    chunk_size = 20
                    for i in range(0, len(content), chunk_size):
                        yield {"type": "chunk", "text": content[i:i + chunk_size]}
                    yield {"type": "done"}
                    return
                elif event["type"] == "agent_error":
                    logger.warning(f"Agent stream error: {event['error']}, falling back")
                    # Agent 失败，回退到纯 prompt 模式
                    break
                else:
                    # thinking / tool_start / tool_done 进度事件
                    yield event

        # 回退：纯 prompt 流式模式
        self._ensure_init()
        if not self.is_available():
            yield {"type": "error", "message": "AI 服务未配置，请检查 GEMINI_API_KEY 或 OPENAI_API_KEY 环境变量。"}
            return

        config = get_config()
        temperature = getattr(config, "gemini_temperature", 0.3)
        full_system = f"{self.SYSTEM_PROMPT}\n\n## 当前报告数据\n{report_context}"

        try:
            if self._use_openai and self._openai_client:
                for text in self._stream_openai(full_system, messages, config):
                    yield {"type": "chunk", "text": text}
            else:
                for text in self._stream_gemini(full_system, messages, temperature):
                    yield {"type": "chunk", "text": text}
        except Exception as e:
            yield {"type": "error", "message": str(e)}
            return
        yield {"type": "done"}

    def _stream_gemini(
        self, system: str, messages: List[Dict[str, str]],
        temperature: float,
    ) -> Iterator[str]:
        """Gemini 流式对话"""
        contents = self._build_gemini_contents(system, messages)
        gen_cfg = {"temperature": temperature}
        models = [self._model]
        if self._model_fallback:
            models.append(self._model_fallback)

        last_err = None
        for model in models:
            try:
                resp = model.generate_content(
                    contents,
                    generation_config=gen_cfg,
                    stream=True,
                )
                for chunk in resp:
                    if chunk.text:
                        yield chunk.text
                return
            except Exception as e:
                last_err = e
                logger.warning(f"Chat stream Gemini 失败: {e}")

        yield f"AI 回复失败: {last_err}"

    def _stream_openai(
        self, system: str, messages: List[Dict[str, str]],
        config: Any,
    ) -> Iterator[str]:
        """OpenAI 流式对话"""
        oai_messages = [{"role": "system", "content": system}]
        for msg in messages:
            oai_messages.append({"role": msg["role"], "content": msg["content"]})

        try:
            stream = self._openai_client.chat.completions.create(
                model=config.openai_model,
                messages=oai_messages,
                temperature=getattr(config, "openai_temperature", 0.3),
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        except Exception as e:
            logger.error(f"Chat stream OpenAI 失败: {e}")
            yield f"AI 回复失败: {e}"


# 单例
_chat_service: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service

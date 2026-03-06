# -*- coding: utf-8 -*-
"""
Agent 执行引擎 - 基于 Gemini/OpenAI function calling 的 ReAct 循环
"""

import json
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable

from src.agent.tools import TOOL_DEFINITIONS, TOOL_FUNCTIONS, TOOL_DISPLAY_NAMES

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5  # 最多工具调用轮次，防止死循环


@dataclass
class AgentResult:
    success: bool
    content: str
    error: Optional[str] = None
    tool_calls: List[Dict] = field(default_factory=list)
    total_steps: int = 0


SYSTEM_PROMPT = """你是一位专业的A股投资分析助手，具备主动获取数据的能力。

## 你的能力
你可以调用以下工具来获取最新数据：
- **get_realtime_quote**: 获取股票实时价格、涨跌幅、成交量
- **get_daily_history**: 获取历史K线、均线数据
- **get_chip_distribution**: 获取筹码分布（获利盘、成本区间）
- **get_analysis_context**: 读取已有分析报告的详细数据
- **search_stock_news**: 搜索最新新闻、公告、机构动向

## 工作原则
1. **主动获取数据**：用户提问时，先调用相关工具获取最新数据，再给出分析
2. **数据驱动**：所有结论必须基于工具返回的真实数据，禁止编造
3. **简洁专业**：用简洁的中文给出专业分析，避免冗长
4. **风险提示**：分析结尾注明"以上分析仅供参考，不构成投资建议"

## 重要约束
- 如果工具返回 error 字段，说明数据获取失败，如实告知用户
- 不要在没有数据支撑的情况下给出具体的买卖点位
- 涉及持仓建议时，提醒用户结合自身风险承受能力决策
"""


class AgentExecutor:
    """Agent 执行引擎，支持 Gemini 和 OpenAI function calling"""

    def __init__(self, config):
        self._config = config
        self._model = None
        self._openai_client = None
        self._use_openai = False
        self._initialized = False

    def _ensure_init(self):
        if self._initialized:
            return
        self._initialized = True
        config = self._config

        api_key = config.gemini_api_key
        if api_key and "your_" not in api_key:
            try:
                from google import genai
                self._genai_client = genai.Client(api_key=api_key)
                self._gemini_model_name = config.gemini_model
                self._model = True  # 标记已初始化
                logger.info("Agent: Gemini function calling 初始化成功 (google.genai)")
            except Exception as e:
                logger.warning(f"Agent: Gemini 初始化失败: {e}")

        if not self._model and config.openai_api_key:
            try:
                from openai import OpenAI
                self._openai_client = OpenAI(
                    api_key=config.openai_api_key,
                    base_url=config.openai_base_url,
                )
                self._use_openai = True
                logger.info("Agent: OpenAI function calling 初始化成功")
            except Exception as e:
                logger.warning(f"Agent: OpenAI 初始化失败: {e}")

    def is_available(self) -> bool:
        self._ensure_init()
        return (self._model is not None and hasattr(self, '_genai_client')) or self._openai_client is not None

    def _build_genai_tools(self):
        """将工具定义转换为 google.genai Tool 格式"""
        from google.genai import types as genai_types

        declarations = []
        for tool_def in TOOL_DEFINITIONS:
            params = tool_def["parameters"]
            props = {}
            for name, spec in params.get("properties", {}).items():
                prop = {"type": spec["type"], "description": spec.get("description", "")}
                props[name] = prop

            declarations.append(genai_types.FunctionDeclaration(
                name=tool_def["name"],
                description=tool_def["description"],
                parameters=genai_types.Schema(
                    type=genai_types.Type.OBJECT,
                    properties={k: genai_types.Schema(
                        type=genai_types.Type.STRING if v["type"] == "string" else genai_types.Type.INTEGER,
                        description=v.get("description", ""),
                    ) for k, v in props.items()},
                    required=params.get("required", []),
                ),
            ))
        return [genai_types.Tool(function_declarations=declarations)]

    def _build_openai_tools(self):
        """将工具定义转换为 OpenAI tools 格式"""
        return [{"type": "function", "function": tool_def} for tool_def in TOOL_DEFINITIONS]

    def _execute_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        """执行工具调用，返回 JSON 字符串结果"""
        func = TOOL_FUNCTIONS.get(tool_name)
        if not func:
            return json.dumps({"error": f"未知工具: {tool_name}"}, ensure_ascii=False)
        try:
            result = func(**tool_args)
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            logger.error(f"Tool {tool_name} execution error: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def chat(
        self,
        message: str,
        session_id: str = "",
        history: Optional[List[Dict]] = None,
        progress_callback: Optional[Callable[[Dict], None]] = None,
        context: Optional[Dict[str, Any]] = None,
        strategy_id: Optional[str] = None,
    ) -> AgentResult:
        """执行一轮 Agent 对话（含多轮工具调用）"""
        self._ensure_init()
        if not self.is_available():
            return AgentResult(success=False, content="", error="AI 服务未配置")

        # 如果有报告上下文，注入到消息中
        user_message = message
        if context:
            ctx_str = json.dumps(context, ensure_ascii=False, default=str)
            user_message = f"[当前分析报告上下文]\n{ctx_str}\n\n[用户问题]\n{message}"

        # 构建策略增强的 system prompt
        system_prompt = SYSTEM_PROMPT
        if strategy_id:
            try:
                from src.agent.strategy_manager import get_strategy_system_prompt
                addon = get_strategy_system_prompt(strategy_id)
                if addon:
                    system_prompt = SYSTEM_PROMPT + "\n\n" + addon
                    logger.debug(f"[Agent] 已应用策略: {strategy_id}")
            except Exception as e:
                logger.warning(f"[Agent] 策略加载失败({strategy_id}): {e}")

        if self._use_openai:
            return self._chat_openai(user_message, history or [], progress_callback, system_prompt)
        return self._chat_gemini(user_message, history or [], progress_callback, system_prompt)

    def _chat_gemini(
        self,
        message: str,
        history: List[Dict],
        progress_callback: Optional[Callable],
        system_prompt: str = SYSTEM_PROMPT,
    ) -> AgentResult:
        """Gemini function calling 循环 (google.genai SDK)"""
        from google.genai import types as genai_types
        from concurrent.futures import ThreadPoolExecutor

        config = self._config
        temperature = getattr(config, "gemini_temperature", 0.3)
        timeout = getattr(config, "gemini_request_timeout", 120)
        client = self._genai_client
        model_name = self._gemini_model_name
        tools = self._build_genai_tools()

        # 构建对话历史（google.genai Content 格式）
        contents = []
        for msg in history:
            role = "model" if msg.get("role") == "assistant" else "user"
            contents.append(genai_types.Content(
                role=role,
                parts=[genai_types.Part.from_text(text=msg.get("content", ""))]
            ))
        contents.append(genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=message)]
        ))

        gen_config = genai_types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_prompt,
            tools=tools,
        )

        tool_calls_log = []
        total_steps = 0

        for round_num in range(MAX_TOOL_ROUNDS + 1):
            total_steps += 1
            try:
                if progress_callback and round_num == 0:
                    progress_callback({"type": "thinking"})

                with ThreadPoolExecutor(max_workers=1) as tp:
                    future = tp.submit(
                        client.models.generate_content,
                        model=model_name,
                        contents=contents,
                        config=gen_config,
                    )
                    resp = future.result(timeout=timeout)

            except Exception as e:
                logger.error(f"Gemini generate_content failed: {e}")
                return AgentResult(success=False, content="", error=str(e), total_steps=total_steps)

            # 检查是否有 function call
            candidate = resp.candidates[0] if resp.candidates else None
            if not candidate:
                break

            # 收集所有 function calls 和文本
            function_calls = []
            text_parts = []
            for part in candidate.content.parts:
                if part.function_call and part.function_call.name:
                    function_calls.append(part.function_call)
                elif part.text:
                    text_parts.append(part.text)

            if not function_calls:
                final_text = "\n".join(text_parts) if text_parts else ""
                return AgentResult(
                    success=True,
                    content=final_text,
                    tool_calls=tool_calls_log,
                    total_steps=total_steps,
                )

            if round_num >= MAX_TOOL_ROUNDS:
                final_text = "\n".join(text_parts) if text_parts else "（已达到最大工具调用轮次）"
                return AgentResult(
                    success=True,
                    content=final_text,
                    tool_calls=tool_calls_log,
                    total_steps=total_steps,
                )

            # 将模型回复（含 function calls）加入历史
            contents.append(candidate.content)

            # 执行所有工具调用，收集结果
            tool_response_parts = []
            for fc in function_calls:
                tool_name = fc.name
                tool_args = dict(fc.args) if fc.args else {}
                display_name = TOOL_DISPLAY_NAMES.get(tool_name, tool_name)

                if progress_callback:
                    progress_callback({"type": "tool_start", "tool": tool_name, "display_name": display_name, "args": tool_args})

                result_str = self._execute_tool(tool_name, tool_args)
                tool_calls_log.append({"tool": tool_name, "args": tool_args, "result": result_str})

                if progress_callback:
                    progress_callback({"type": "tool_done", "tool": tool_name, "display_name": display_name})

                tool_response_parts.append(
                    genai_types.Part.from_function_response(
                        name=tool_name,
                        response={"result": result_str},
                    )
                )

            # 将工具结果加入历史
            contents.append(genai_types.Content(
                role="user",
                parts=tool_response_parts,
            ))

            if progress_callback:
                progress_callback({"type": "thinking"})

        return AgentResult(success=False, content="", error="Agent 循环异常退出", total_steps=total_steps)

    def _chat_openai(
        self,
        message: str,
        history: List[Dict],
        progress_callback: Optional[Callable],
        system_prompt: str = SYSTEM_PROMPT,
    ) -> AgentResult:
        """OpenAI function calling 循环"""
        config = self._config
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
        messages.append({"role": "user", "content": message})

        tools = self._build_openai_tools()
        tool_calls_log = []
        total_steps = 0

        for round_num in range(MAX_TOOL_ROUNDS + 1):
            total_steps += 1
            try:
                if progress_callback and round_num == 0:
                    progress_callback({"type": "thinking"})

                resp = self._openai_client.chat.completions.create(
                    model=config.openai_model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=getattr(config, "openai_temperature", 0.3),
                    timeout=getattr(config, "gemini_request_timeout", 120),
                )
            except Exception as e:
                logger.error(f"OpenAI chat.completions failed: {e}")
                return AgentResult(success=False, content="", error=str(e), total_steps=total_steps)

            choice = resp.choices[0]
            msg_obj = choice.message

            if not msg_obj.tool_calls:
                # 没有工具调用，返回最终文本
                return AgentResult(
                    success=True,
                    content=msg_obj.content or "",
                    tool_calls=tool_calls_log,
                    total_steps=total_steps,
                )

            if round_num >= MAX_TOOL_ROUNDS:
                return AgentResult(
                    success=True,
                    content=msg_obj.content or "（已达到最大工具调用轮次）",
                    tool_calls=tool_calls_log,
                    total_steps=total_steps,
                )

            # 将模型回复加入历史
            messages.append({"role": "assistant", "content": msg_obj.content, "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg_obj.tool_calls
            ]})

            # 执行工具调用
            for tc in msg_obj.tool_calls:
                tool_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments)
                except Exception:
                    tool_args = {}
                display_name = TOOL_DISPLAY_NAMES.get(tool_name, tool_name)

                if progress_callback:
                    progress_callback({"type": "tool_start", "tool": tool_name, "display_name": display_name, "args": tool_args})

                result_str = self._execute_tool(tool_name, tool_args)
                tool_calls_log.append({"tool": tool_name, "args": tool_args, "result": result_str})

                if progress_callback:
                    progress_callback({"type": "tool_done", "tool": tool_name, "display_name": display_name})

                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

            if progress_callback:
                progress_callback({"type": "thinking"})

        return AgentResult(success=False, content="", error="Agent 循环异常退出", total_steps=total_steps)

# -*- coding: utf-8 -*-
"""
统一 Gemini / OpenAI LLM 客户端

职责：
1. 封装 google.genai 新版 SDK，提供 generate / generate_json / generate_stream / generate_with_tools 四种调用模式
2. 内置重试 + fallback（主模型 → 备选模型 → OpenAI）
3. 每次调用自动记录 token 到 TokenTracker
4. 不依赖 src.config，Config 通过构造参数注入
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, Iterator, Optional

from src.llm.token_tracker import TokenTracker
from src.llm.types import CallMode, LLMResponse

logger = logging.getLogger(__name__)

MODEL_PRO = "pro"
MODEL_FLASH = "flash"


def _is_retryable(e: Exception) -> bool:
    """判断异常是否可重试（与 analyzer.py 保持一致）"""
    s = str(e).lower()
    return any(kw in s for kw in ("499", "timeout", "deadline", "closed", "429", "rate", "resource"))


class GeminiClient:
    """统一的 Gemini/OpenAI LLM 客户端"""

    def __init__(self, config: Any) -> None:
        self._config = config
        self._genai_client: Any = None
        self._openai_client: Any = None
        self._initialized = False
        self._tracker = TokenTracker.get_instance()

    def _ensure_init(self) -> None:
        """延迟初始化：首次调用时才创建 SDK 客户端"""
        if self._initialized:
            return
        self._initialized = True
        cfg = self._config

        api_key = getattr(cfg, "gemini_api_key", None)
        if api_key and "your_" not in api_key:
            try:
                from google import genai
                self._genai_client = genai.Client(api_key=api_key)
                logger.info("GeminiClient: google.genai 初始化成功")
            except Exception as e:
                logger.warning("GeminiClient: google.genai 初始化失败: %s", e)

        openai_key = getattr(cfg, "openai_api_key", None)
        if openai_key:
            try:
                from openai import OpenAI
                self._openai_client = OpenAI(
                    api_key=openai_key,
                    base_url=getattr(cfg, "openai_base_url", None),
                )
                logger.info("GeminiClient: OpenAI 兼容客户端初始化成功")
            except Exception as e:
                logger.warning("GeminiClient: OpenAI 初始化失败: %s", e)

    def is_available(self) -> bool:
        self._ensure_init()
        return self._genai_client is not None or self._openai_client is not None

    # ------------------------------------------------------------------
    # 模型名解析
    # ------------------------------------------------------------------
    def _resolve_model(self, model: Optional[str]) -> str:
        """将 'pro' / 'flash' / None 映射为 config 中的实际模型名"""
        cfg = self._config
        if model is None or model == MODEL_PRO:
            return getattr(cfg, "gemini_model", "gemini-3-pro-preview")
        if model == MODEL_FLASH:
            return getattr(cfg, "gemini_model_when_cached", None) or getattr(
                cfg, "gemini_model_fallback", "gemini-3-flash-preview"
            )
        return model

    def _resolve_fallback(self, primary: str) -> Optional[str]:
        """返回主模型对应的 fallback 模型名，不同于主模型时才返回"""
        cfg = self._config
        fb = getattr(cfg, "gemini_model_fallback", None)
        if fb and fb != primary:
            return fb
        return None

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _get_max_retries(self) -> int:
        return max(1, getattr(self._config, "gemini_max_retries", 5))

    def _get_retry_delay(self) -> float:
        return getattr(self._config, "gemini_retry_delay", 5.0)

    def _get_timeout(self, override: Optional[int]) -> int:
        if override is not None:
            return override
        return getattr(self._config, "gemini_request_timeout", 120)

    def _get_temperature(self, override: Optional[float]) -> float:
        if override is not None:
            return override
        return getattr(self._config, "gemini_temperature", 0.2)

    def _record_tokens(
        self,
        scene: str,
        model: str,
        response: Any,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> tuple:
        """从 response.usage_metadata 提取 token 数并记录"""
        in_tok = input_tokens
        out_tok = output_tokens
        usage = getattr(response, "usage_metadata", None)
        if usage:
            in_tok = getattr(usage, "prompt_token_count", 0) or in_tok
            out_tok = getattr(usage, "candidates_token_count", 0) or out_tok
        if in_tok or out_tok:
            self._tracker.record(scene, model, in_tok, out_tok)
        return in_tok, out_tok

    def _call_openai(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float,
        timeout: int,
        scene: str,
        *,
        json_mode: bool = False,
    ) -> LLMResponse:
        """OpenAI 兼容 API 调用"""
        cfg = self._config
        model_name = getattr(cfg, "openai_model", "gpt-4o-mini")
        temp = temperature if temperature is not None else getattr(cfg, "openai_temperature", 0.2)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        kwargs: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temp,
            "timeout": timeout,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        t0 = time.monotonic()
        resp = self._openai_client.chat.completions.create(**kwargs)
        latency = int((time.monotonic() - t0) * 1000)

        text = resp.choices[0].message.content or ""
        usage = resp.usage
        in_tok = getattr(usage, "prompt_tokens", 0) if usage else 0
        out_tok = getattr(usage, "completion_tokens", 0) if usage else 0
        self._tracker.record(scene, model_name, in_tok, out_tok)

        json_data = None
        if json_mode:
            try:
                json_data = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                pass

        return LLMResponse(
            text=text,
            json_data=json_data,
            model_used=model_name,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=latency,
            success=True,
        )

    # ------------------------------------------------------------------
    # 公开方法 1：文本生成（非流式）
    # ------------------------------------------------------------------
    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
        scene: str = "default",
    ) -> LLMResponse:
        """文本生成（非流式），带重试和 fallback"""
        self._ensure_init()
        return self._generate_internal(
            prompt,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            timeout=timeout,
            scene=scene,
            json_mode=False,
        )

    # ------------------------------------------------------------------
    # 公开方法 2：JSON Mode 结构化输出
    # ------------------------------------------------------------------
    def generate_json(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        response_schema: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
        scene: str = "default",
    ) -> LLMResponse:
        """JSON Mode 输出，使用 response_mime_type='application/json' + response_schema"""
        self._ensure_init()
        return self._generate_internal(
            prompt,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            timeout=timeout,
            scene=scene,
            json_mode=True,
            response_schema=response_schema,
        )

    # ------------------------------------------------------------------
    # 公开方法 3：流式文本生成
    # ------------------------------------------------------------------
    def generate_stream(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        scene: str = "default",
    ) -> Iterator[str]:
        """流式文本生成，yield 每个 chunk 的文本"""
        self._ensure_init()

        if not self._genai_client:
            raise RuntimeError("Gemini 客户端未初始化，流式输出暂不支持 OpenAI fallback")

        from google.genai import types as genai_types

        model_name = self._resolve_model(model)
        temp = self._get_temperature(temperature)

        gen_config = genai_types.GenerateContentConfig(
            temperature=temp,
        )
        if system_prompt:
            gen_config.system_instruction = system_prompt

        total_text = ""
        try:
            stream = self._genai_client.models.generate_content_stream(
                model=model_name,
                contents=prompt,
                config=gen_config,
            )
            for chunk in stream:
                if chunk.text:
                    total_text += chunk.text
                    yield chunk.text
            usage = getattr(chunk, "usage_metadata", None) if chunk else None
            in_tok = getattr(usage, "prompt_token_count", 0) if usage else 0
            out_tok = getattr(usage, "candidates_token_count", 0) if usage else 0
            if in_tok or out_tok:
                self._tracker.record(scene, model_name, in_tok, out_tok)
        except Exception as e:
            logger.error("GeminiClient stream 异常: %s", e)
            raise

    # ------------------------------------------------------------------
    # 公开方法 4：Function Calling
    # ------------------------------------------------------------------
    def generate_with_tools(
        self,
        contents: Any,
        *,
        tools: Any,
        system_prompt: str = "",
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
        scene: str = "default",
    ) -> Any:
        """Function calling 模式，返回原始 response 让调用方处理工具循环"""
        self._ensure_init()

        if not self._genai_client:
            raise RuntimeError("Gemini 客户端未初始化，function calling 不可用")

        from google.genai import types as genai_types

        model_name = self._resolve_model(model)
        temp = self._get_temperature(temperature)
        api_timeout = self._get_timeout(timeout)

        gen_config = genai_types.GenerateContentConfig(
            temperature=temp,
            tools=tools,
        )
        if system_prompt:
            gen_config.system_instruction = system_prompt

        with ThreadPoolExecutor(max_workers=1) as tp:
            future = tp.submit(
                self._genai_client.models.generate_content,
                model=model_name,
                contents=contents,
                config=gen_config,
            )
            try:
                resp = future.result(timeout=api_timeout)
            except FuturesTimeoutError:
                raise TimeoutError(f"Gemini function calling 请求超时 ({api_timeout}s)")

        self._record_tokens(scene, model_name, resp)
        return resp

    # ------------------------------------------------------------------
    # 内部核心：重试 + fallback 引擎
    # ------------------------------------------------------------------
    def _generate_internal(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
        scene: str = "default",
        json_mode: bool = False,
        response_schema: Optional[Dict[str, Any]] = None,
    ) -> LLMResponse:
        """统一的重试 + fallback 生成引擎"""
        max_retries = self._get_max_retries()
        retry_delay = self._get_retry_delay()
        api_timeout = self._get_timeout(timeout)
        temp = self._get_temperature(temperature)

        primary_model = self._resolve_model(model)
        fallback_model = self._resolve_fallback(primary_model)

        models_to_try = []
        if self._genai_client:
            models_to_try.append(("gemini", primary_model, "主模型"))
            if fallback_model:
                models_to_try.append(("gemini", fallback_model, "备选模型"))
        if self._openai_client:
            models_to_try.append(("openai", getattr(self._config, "openai_model", "gpt-4o-mini"), "OpenAI"))

        if not models_to_try:
            return LLMResponse(success=False, error="无可用 AI 模型")

        last_err: Optional[Exception] = None
        for api_type, model_name, label in models_to_try:
            for attempt in range(max_retries):
                t0 = time.monotonic()
                try:
                    if api_type == "openai":
                        return self._call_openai(
                            prompt, system_prompt, temp, api_timeout, scene,
                            json_mode=json_mode,
                        )
                    resp = self._call_gemini_once(
                        prompt,
                        system_prompt=system_prompt,
                        model_name=model_name,
                        temperature=temp,
                        timeout=api_timeout,
                        json_mode=json_mode,
                        response_schema=response_schema,
                    )
                    latency = int((time.monotonic() - t0) * 1000)
                    in_tok, out_tok = self._record_tokens(scene, model_name, resp)

                    text = resp.text or ""
                    json_data = None
                    if json_mode:
                        try:
                            json_data = json.loads(text)
                        except (json.JSONDecodeError, ValueError):
                            pass

                    return LLMResponse(
                        text=text,
                        json_data=json_data,
                        model_used=model_name,
                        input_tokens=in_tok,
                        output_tokens=out_tok,
                        latency_ms=latency,
                        success=True,
                    )

                except Exception as e:
                    last_err = e
                    latency = int((time.monotonic() - t0) * 1000)
                    if attempt < max_retries - 1 and _is_retryable(e):
                        wait = retry_delay * (attempt + 1)
                        logger.warning(
                            "GeminiClient %s 异常, %0.fs 后重试 (%d/%d): %s",
                            label, wait, attempt + 1, max_retries, e,
                        )
                        time.sleep(wait)
                    else:
                        logger.warning("GeminiClient %s 失败, 尝试下一可用模型: %s", label, e)
                        break

        error_msg = str(last_err) if last_err else "所有模型均失败"
        return LLMResponse(success=False, error=error_msg)

    def _call_gemini_once(
        self,
        prompt: str,
        *,
        system_prompt: str,
        model_name: str,
        temperature: float,
        timeout: int,
        json_mode: bool,
        response_schema: Optional[Dict[str, Any]],
    ) -> Any:
        """执行单次 Gemini API 调用"""
        from google.genai import types as genai_types

        gen_config = genai_types.GenerateContentConfig(
            temperature=temperature,
        )
        if system_prompt:
            gen_config.system_instruction = system_prompt
        if json_mode:
            gen_config.response_mime_type = "application/json"
            if response_schema:
                gen_config.response_schema = response_schema

        with ThreadPoolExecutor(max_workers=1) as tp:
            future = tp.submit(
                self._genai_client.models.generate_content,
                model=model_name,
                contents=prompt,
                config=gen_config,
            )
            try:
                return future.result(timeout=timeout)
            except FuturesTimeoutError:
                raise TimeoutError(f"Gemini API 请求超时 ({timeout}s)")

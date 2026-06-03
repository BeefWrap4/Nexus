"""LLM客户端.

基于WAT agent/llm_client.py 复用升级:
- 接入LiteLLM Proxy（统一网关）
- 保留全局并发控制
- 保留Fallback链
- 增加流式输出支持
- 真正解析LiteLLM Proxy的响应格式
- 支持 content / reasoning_content / reasoning 提取
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

import httpx

from nexus.config import settings
from nexus.exceptions import LLMCallException


@dataclass
class LLMResponse:
    """标准化的LLM响应.

    统一不同Provider（OpenAI / Anthropic / DeepSeek等）的响应格式。
    """

    content: str = ""
    reasoning_content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def reasoning(self) -> str:
        """兼容属性：返回推理内容（reasoning_content 或 reasoning）."""
        return self.reasoning_content

    @property
    def total_tokens(self) -> int:
        return self.usage.get("total_tokens", 0)

    @property
    def prompt_tokens(self) -> int:
        return self.usage.get("prompt_tokens", 0)

    @property
    def completion_tokens(self) -> int:
        return self.usage.get("completion_tokens", 0)


@dataclass
class LLMStreamChunk:
    """流式输出块."""

    content: str = ""
    reasoning_content: str = ""
    finish_reason: Optional[str] = None
    tool_call: Optional[dict] = None
    model: str = ""


class LLMClient:
    """LLM客户端.

    对应WAT agent/llm_client.py。
    通过LiteLLM Proxy统一接入所有Provider。
    真正解析LiteLLM Proxy返回的OpenAI兼容格式响应。
    """

    def __init__(
        self,
        proxy_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 120.0,
    ):
        self.proxy_url = proxy_url or settings.LITELLM_PROXY_URL
        self.api_key = api_key or settings.LITELLM_API_KEY
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取HTTP客户端（懒加载）."""
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.proxy_url,
                timeout=self.timeout,
                headers=headers,
            )
        return self._client

    # ------------------------------------------------------------------
    # 响应解析
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_content(choice: dict[str, Any]) -> str:
        """从choice中提取content字段.

        兼容OpenAI格式：choice["message"]["content"]
        兼容流式格式：choice["delta"]["content"]
        """
        message = choice.get("message") or choice.get("delta", {})
        content = message.get("content")
        return content if content is not None else ""

    @staticmethod
    def _extract_reasoning(choice: dict[str, Any]) -> str:
        """从choice中提取reasoning_content / reasoning字段.

        兼容DeepSeek格式：delta["reasoning_content"]
        兼容Anthropic格式：delta["reasoning"]
        """
        message = choice.get("message") or choice.get("delta", {})
        reasoning = message.get("reasoning_content") or message.get("reasoning", "")
        return reasoning if reasoning is not None else ""

    @staticmethod
    def _extract_tool_calls(choice: dict[str, Any]) -> list[dict]:
        """从choice中提取tool_calls字段."""
        message = choice.get("message") or choice.get("delta", {})
        tool_calls = message.get("tool_calls")
        if not tool_calls:
            return []
        return tool_calls if isinstance(tool_calls, list) else []

    @staticmethod
    def _extract_usage(raw: dict[str, Any]) -> dict[str, int]:
        """从原始响应中提取usage信息."""
        usage = raw.get("usage", {})
        return {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

    def _parse_response(self, raw: dict[str, Any]) -> LLMResponse:
        """解析LiteLLM Proxy返回的OpenAI兼容格式响应.

        Args:
            raw: LiteLLM Proxy返回的JSON字典。

        Returns:
            标准化的LLMResponse。
        """
        choices = raw.get("choices", [])
        if not choices:
            return LLMResponse(raw=raw)

        choice = choices[0]
        content = self._extract_content(choice)
        reasoning = self._extract_reasoning(choice)
        tool_calls = self._extract_tool_calls(choice)
        usage = self._extract_usage(raw)

        return LLMResponse(
            content=content,
            reasoning_content=reasoning,
            tool_calls=tool_calls,
            model=raw.get("model", ""),
            usage=usage,
            raw=raw,
        )

    # ------------------------------------------------------------------
    # 非流式调用
    # ------------------------------------------------------------------

    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = "gpt-4o",
        provider: str = "openai",
        temperature: float = 0.7,
        max_tokens: int = 4000,
        tools: Optional[list[dict]] = None,
        response_format: Optional[dict] = None,
        **extra_params: Any,
    ) -> LLMResponse:
        """调用LLM（非流式）.

        对应WAT BaseAgent._try_llm_call()。
        真正解析LiteLLM Proxy的响应，返回标准化的LLMResponse。

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            model: 模型名称（通过LiteLLM Proxy路由）
            provider: Provider标识（用于fallback链）
            temperature: 温度参数
            max_tokens: 最大token数
            tools: 可用工具列表（OpenAI格式）
            response_format: 响应格式（如 {"type": "json_object"}）
            **extra_params: 额外参数透传给LiteLLM Proxy

        Returns:
            标准化的LLMResponse对象
        """
        client = await self._get_client()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        if response_format:
            payload["response_format"] = response_format

        # 透传额外参数
        payload.update(extra_params)

        from nexus.observability.llm_tracer import trace_llm_call

        try:
            async with trace_llm_call(
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                provider=provider,
            ) as tracer:
                response = await client.post("/chat/completions", json=payload)
                response.raise_for_status()
                raw = response.json()
                result = self._parse_response(raw)
                tracer.set_response(result)
                return result
        except httpx.HTTPStatusError as e:
            raise LLMCallException(
                f"HTTP {e.response.status_code}: {e.response.text}",
                provider=provider,
            )
        except json.JSONDecodeError as e:
            raise LLMCallException(f"Invalid JSON response: {e}", provider=provider)
        except Exception as e:
            raise LLMCallException(str(e), provider=provider)

    # ------------------------------------------------------------------
    # 流式调用
    # ------------------------------------------------------------------

    async def stream_call(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 4000,
        tools: Optional[list[dict]] = None,
        **extra_params: Any,
    ) -> AsyncIterator[LLMStreamChunk]:
        """流式调用LLM.

        通过SSE (Server-Sent Events) 逐块接收响应。
        兼容OpenAI格式和LiteLLM Proxy的统一格式。

        Yields:
            LLMStreamChunk: 每个流式块包含增量内容、推理内容、tool_call等。
        """
        client = await self._get_client()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        payload.update(extra_params)

        try:
            async with client.stream(
                "POST", "/chat/completions", json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or line.startswith(":"):
                        # 忽略空行和SSE注释行
                        continue
                    if not line.startswith("data: "):
                        continue

                    data = line[6:]
                    if data == "[DONE]":
                        break

                    try:
                        chunk_raw = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk_raw.get("choices", [])
                    if not choices:
                        continue

                    choice = choices[0]
                    delta = choice.get("delta", {})

                    yield LLMStreamChunk(
                        content=delta.get("content") or "",
                        reasoning_content=delta.get("reasoning_content")
                        or delta.get("reasoning")
                        or "",
                        finish_reason=choice.get("finish_reason"),
                        tool_call=delta.get("tool_calls", [None])[0]
                        if delta.get("tool_calls")
                        else None,
                        model=chunk_raw.get("model", ""),
                    )
        except httpx.HTTPStatusError as e:
            raise LLMCallException(
                f"HTTP {e.response.status_code}: {e.response.text}",
                provider="",
            )
        except Exception as e:
            raise LLMCallException(str(e), provider="")

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------

    async def call_with_fallback(
        self,
        system_prompt: str,
        user_prompt: str,
        models: list[str],
        **kwargs: Any,
    ) -> LLMResponse:
        """带Fallback链的LLM调用.

        按models列表顺序依次尝试，直到成功。

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            models: 模型Fallback链，如 ["gpt-4o", "claude-sonnet-4", "deepseek-chat"]
            **kwargs: 其他call参数

        Returns:
            第一个成功响应的LLMResponse

        Raises:
            LLMCallException: 所有模型都失败时抛出最后一个异常。
        """
        last_error: Optional[Exception] = None
        for model in models:
            try:
                return await self.call(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model=model,
                    **kwargs,
                )
            except LLMCallException as e:
                last_error = e
                continue
        raise last_error or LLMCallException("All models in fallback chain failed")

    async def close(self) -> None:
        """关闭客户端，释放HTTP连接池."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "LLMClient":
        """异步上下文管理器入口."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文管理器出口."""
        await self.close()

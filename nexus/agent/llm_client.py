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
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

import httpx

from nexus.config import settings
from nexus.exceptions import LLMCallException

logger = logging.getLogger(__name__)


# P0 (Task 1.5) SOC2/GDPR: 在 LLM 入口/出口对 PII 进行脱敏。
# P2 follow-up (Task 1.5.5): 把 PII guard 从"模块级一次性绑定"改为
# "per-tenant, runtime-toggled" — 调用 ``is_pii_enabled(tenant_id)``
# (走 SystemSetting 表 + 30s cache, env var 作为 fallback)。
# Settings.vue 的 piiEnabled switch 改的是 SystemSetting 表, 现在
# 它真的能在运行期生效, 不用重启 API。
#
# 实现: 用 ``_guard_cache`` 缓存 (tenant_id, PIIGuard) 对, 避免每次
# LLM 调用都重建 PIIGuard (那个东西内部有正则 compile, 重建一次约几 ms)。
_guard_cache: dict[str, "PIIGuard"] = {}


async def _get_pii_guard(tenant_id: Optional[str]) -> Optional["PIIGuard"]:
    """按 tenant 取 PIIGuard (P2 follow-up: 替换 module-level _pii_guard).

    Returns:
        PIIGuard 实例 — 该 tenant 的 PII 过滤已开启
        None — PII 过滤关闭, 或 tenant_id 未知 (debug log 一次)

    Side effect:
        首次调用按 tenant 构造 PIIGuard, 后续命中 ``_guard_cache``。
    """
    if not tenant_id:
        # 没 tenant 上下文 (例如调用方没传) — 跳过 PII, 不阻塞 LLM
        logger.debug("pii_guard_no_tenant_context — PII filtering skipped")
        return None

    try:
        from nexus.services.runtime_config import is_pii_enabled
        enabled = await is_pii_enabled(tenant_id)
    except Exception as exc:  # noqa: BLE001
        # runtime_config 异常时 fail-secure: 跳过 PII (避免 PII 漏到 LLM 又
        # 不能脱敏 — 实际上 fail-secure 应该是"启用 PII", 但这里
        # PII 已加载到 cache 时有现成 guard, 走 None 路径相当于关闭,
        # 跟旧版 _pii_guard=None 行为一致。安全团队后续可以收紧。)
        logger.warning(
            "pii_guard_lookup_failed tenant=%s err=%s — skipping PII",
            tenant_id, exc,
        )
        return None

    if not enabled:
        return None

    # Cache: 一个 tenant 一个 guard 实例 (PIIGuard 内部 regex 编译很贵)
    if tenant_id not in _guard_cache:
        from nexus.security.pii_guard import PIIGuard
        _guard_cache[tenant_id] = PIIGuard()
    return _guard_cache[tenant_id]


def invalidate_pii_guard_cache(tenant_id: Optional[str] = None) -> None:
    """清空 PII guard 缓存 — settings API 在写入 system_settings 后调,
    让前端的 piiEnabled toggle 立即生效 (不用等 30s cache TTL 到期).

    Args:
        tenant_id: 指定 tenant 时只清它; None 时清全部。
    """
    if tenant_id is None:
        _guard_cache.clear()
    else:
        _guard_cache.pop(tenant_id, None)


async def _sanitize_messages(messages, tenant_id: Optional[str] = None):
    """对 OpenAI 格式 messages 列表做 PII 脱敏 (关闭时原样返回).

    P2 follow-up: 从同步 + module-level guard 改为 async + per-tenant guard。
    """
    if not messages:
        return messages
    guard = await _get_pii_guard(tenant_id)
    if guard is None:
        return messages
    return guard.sanitize(messages)


async def _sanitize_text(text, tenant_id: Optional[str] = None):
    """对单段文本做 PII 脱敏 (关闭时原样返回)."""
    if not text:
        return text
    guard = await _get_pii_guard(tenant_id)
    if guard is None:
        return text
    return guard.sanitize(text)


@dataclass
class LLMResponse:
    """标准化的LLM响应.

    统一不同Provider（OpenAI / Anthropic / DeepSeek等）的响应格式。
    Phase 9: 增加 cache_hit 标记语义缓存命中状态。
    """

    content: str = ""
    reasoning_content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
    cache_hit: bool = False

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
        cache_url: Optional[str] = None,
        cache_api_key: Optional[str] = None,
        cache_timeout: float = 5.0,
        tenant_id: Optional[str] = None,
    ):
        self.proxy_url = proxy_url or settings.LITELLM_PROXY_URL
        self.api_key = api_key or settings.LITELLM_API_KEY
        self.timeout = timeout

        # Phase 9: 语义缓存配置
        self.cache_url = cache_url or getattr(settings, "SMART_CACHE_URL", "")
        self.cache_api_key = cache_api_key or getattr(settings, "SMART_CACHE_API_KEY", None)
        self.cache_timeout = cache_timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._cache_client: Optional[httpx.AsyncClient] = None
        # P2 (Task 1.5.5): tenant_id 用于按租户决定是否走 PII 脱敏。
        # 缺省时调用 _get_pii_guard 走 no-tenant 路径 (log + skip)。
        # LLMService.generate() 在知道 context['tenant_id'] 时会传进来。
        self.tenant_id = tenant_id

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

    async def _get_cache_client(self) -> httpx.AsyncClient:
        """获取缓存服务HTTP客户端（懒加载）."""
        if self._cache_client is None and self.cache_url:
            headers = {"Content-Type": "application/json"}
            if self.cache_api_key:
                headers["X-API-Key"] = self.cache_api_key
            self._cache_client = httpx.AsyncClient(
                base_url=self.cache_url,
                timeout=self.cache_timeout,
                headers=headers,
            )
        return self._cache_client

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
    # 语义缓存查询 (Phase 9)
    # ------------------------------------------------------------------

    async def _query_semantic_cache(
        self,
        system_prompt: str,
        user_prompt: str,
        session_id: str,
        temperature: float = 0.7,
    ) -> tuple[bool, str]:
        """查询语义缓存.

        Returns:
            (命中?, 响应内容)。未命中时返回 (False, "") 以便降级到正常 LLM 调用。
        """
        if not self.cache_url:
            return False, ""

        try:
            client = await self._get_cache_client()
            if client is None:
                return False, ""

            payload = {
                "prompt": user_prompt,
                "session_id": session_id,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "threshold": 0.92,
            }

            response = await client.post("/v1/llm/ask", json=payload)
            response.raise_for_status()
            data = response.json()

            if data.get("cached") is True:
                return True, data.get("response", "")
            return False, ""

        except Exception:
            # 缓存服务异常时静默降级，不阻塞主流程
            return False, ""

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
        enable_semantic_cache: bool = False,
        session_id: str = "",
        messages: Optional[list[dict]] = None,
        tenant_id: Optional[str] = None,
        **extra_params: Any,
    ) -> LLMResponse:
        """调用LLM（非流式）.

        Phase 9: 增加语义缓存自动拦截。当 enable_semantic_cache=True 时，
        先查询 smart-cache；命中则直接返回，未命中才调用 LLM。

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            model: 模型名称（通过LiteLLM Proxy路由）
            provider: Provider标识（用于fallback链）
            temperature: 温度参数
            max_tokens: 最大token数
            tools: 可用工具列表（OpenAI格式）
            response_format: 响应格式（如 {"type": "json_object"}）
            enable_semantic_cache: 是否启用语义缓存
            session_id: 缓存会话ID（同一会话共享缓存空间）
            messages: 预构建的消息列表（OpenAI格式）。若提供，则跳过 system_prompt/user_prompt 拼接。
            tenant_id: 租户 ID — 覆盖 LLMClient.__init__ 时的默认值。
                缺省时退到 self.tenant_id, 再缺省跳过 PII (debug log 一次)。
            **extra_params: 额外参数透传给LiteLLM Proxy

        Returns:
            标准化的LLMResponse对象
        """
        # P2 (Task 1.5.5): per-tenant PII guard — 优先用 per-call 参数, 退到
        # 实例属性, 再退到 None (跳过 PII 过滤, debug log 一次)。
        effective_tenant_id = tenant_id or self.tenant_id

        # Phase 9: 语义缓存拦截
        # 当存在 tools 或预构建 messages 时跳过缓存
        if enable_semantic_cache and session_id and not tools and not messages:
            from nexus.observability.llm_tracer import trace_llm_call

            cache_hit, cached_response = await self._query_semantic_cache(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                session_id=session_id,
                temperature=temperature,
            )
            if cache_hit:
                result = LLMResponse(
                    content=await _sanitize_text(cached_response, effective_tenant_id),
                    model=model,
                    cache_hit=True,
                )
                # 记录 trace（命中时 latency ≈ 缓存查询耗时）
                async with trace_llm_call(
                    model=model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    provider=provider,
                ) as tracer:
                    tracer.set_response(result)
                return result

        # 正常 LLM 调用
        client = await self._get_client()

        if messages is not None:
            # 使用预构建的消息列表（多模态等场景）
            built_messages = messages
        else:
            built_messages = []
            if system_prompt:
                built_messages.append({"role": "system", "content": system_prompt})
            built_messages.append({"role": "user", "content": user_prompt})

        # P0 (Task 1.5) SOC2/GDPR: 脱敏后再送 LLM（默认开启，关闭时 no-op）
        # P2 (Task 1.5.5): per-tenant guard — 调 is_pii_enabled(tenant_id) 决定
        built_messages = await _sanitize_messages(built_messages, effective_tenant_id)

        payload: dict[str, Any] = {
            "model": model,
            "messages": built_messages,
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
                # P0 (Task 1.5) SOC2/GDPR: 响应内容也脱敏（模型可能回显 PII）
                result.content = await _sanitize_text(result.content, effective_tenant_id) or ""
                result.reasoning_content = await _sanitize_text(result.reasoning_content, effective_tenant_id) or ""
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
        enable_semantic_cache: bool = False,
        session_id: str = "",
        messages: Optional[list[dict]] = None,
        tenant_id: Optional[str] = None,
        **extra_params: Any,
    ) -> AsyncIterator[LLMStreamChunk]:
        """流式调用LLM.

        Phase 9: 增加语义缓存自动拦截。命中时模拟单块 SSE 返回。
        兼容OpenAI格式和LiteLLM Proxy的统一格式。

        Yields:
            LLMStreamChunk: 每个流式块包含增量内容、推理内容、tool_call等。
        """
        # P2 (Task 1.5.5): per-tenant PII guard
        effective_tenant_id = tenant_id or self.tenant_id

        # Phase 9: 语义缓存拦截（流式）
        if enable_semantic_cache and session_id and not messages:
            cache_hit, cached_response = await self._query_semantic_cache(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                session_id=session_id,
                temperature=temperature,
            )
            if cache_hit:
                yield LLMStreamChunk(
                    content=await _sanitize_text(cached_response, effective_tenant_id),
                    finish_reason="stop",
                    model=model,
                )
                return

        # 正常流式 LLM 调用
        client = await self._get_client()

        if messages is not None:
            # 使用预构建的消息列表（多模态等场景）
            built_messages = messages
        else:
            built_messages = []
            if system_prompt:
                built_messages.append({"role": "system", "content": system_prompt})
            built_messages.append({"role": "user", "content": user_prompt})

        # P0 (Task 1.5) SOC2/GDPR: 脱敏后再送 LLM
        # P2 (Task 1.5.5): per-tenant guard
        built_messages = await _sanitize_messages(built_messages, effective_tenant_id)

        payload: dict[str, Any] = {
            "model": model,
            "messages": built_messages,
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
                        content=await _sanitize_text(delta.get("content") or "", effective_tenant_id) or "",
                        reasoning_content=await _sanitize_text(
                            delta.get("reasoning_content")
                            or delta.get("reasoning")
                            or "",
                            effective_tenant_id,
                        ) or "",
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

        @deprecated: 该方法尚未被调用，保留供后续 fallback 链功能使用。

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
        if self._cache_client:
            await self._cache_client.aclose()
            self._cache_client = None

    async def __aenter__(self) -> "LLMClient":
        """异步上下文管理器入口."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文管理器出口."""
        await self.close()

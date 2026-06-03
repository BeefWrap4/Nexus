"""LLM Service - 封装LLM调用，含重试、Fallback链.

作为 nexus/agent/llm_client.py 的上层封装，面向业务层提供：
- 自动重试（指数退避）
- Fallback链（主模型失败自动切换备用模型）
- 接入 LiteLLM Proxy 统一网关
- 流式与非流式接口
- 调用统计与可观测性埋点
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, AsyncIterator, Optional

from nexus.agent.llm_client import LLMClient, LLMResponse, LLMStreamChunk
from nexus.config import settings
from nexus.exceptions import LLMCallException
from nexus.observability.llm_tracer import set_trace_context

logger = logging.getLogger(__name__)


class LLMService:
    """LLM服务层.

    封装LLMClient，提供企业级调用能力：
    1. 自动重试（指数退避 + jitter）
    2. Fallback链（多模型自动切换）
    3. 并发控制（全局Semaphore）
    4. 调用统计（token用量、延迟）
    """

    # 全局并发控制 Semaphore
    _SEMAPHORE: Optional[asyncio.Semaphore] = None

    def __init__(
        self,
        client: Optional[LLMClient] = None,
        fallback_chain: Optional[list[str]] = None,
        max_retries: Optional[int] = None,
        base_delay: Optional[float] = None,
        max_delay: Optional[float] = None,
        backoff_multiplier: Optional[float] = None,
    ):
        """初始化LLMService.

        Args:
            client: LLMClient实例，默认新建。
            fallback_chain: 模型Fallback链，默认从settings读取。
            max_retries: 最大重试次数，默认从settings读取。
            base_delay: 重试基础延迟（秒），默认从settings读取。
            max_delay: 重试最大延迟（秒），默认从settings读取。
            backoff_multiplier: 退避倍数，默认从settings读取。
        """
        self.client = client or LLMClient()
        self.fallback_chain = fallback_chain or settings.LLM_FALLBACK_CHAIN or []
        self.max_retries = max_retries if max_retries is not None else settings.LLM_MAX_RETRIES
        self.base_delay = base_delay if base_delay is not None else settings.LLM_RETRY_BASE_DELAY
        self.max_delay = max_delay if max_delay is not None else settings.LLM_RETRY_MAX_DELAY
        self.backoff_multiplier = (
            backoff_multiplier
            if backoff_multiplier is not None
            else settings.LLM_RETRY_BACKOFF_MULTIPLIER
        )

    # ------------------------------------------------------------------
    # 并发控制
    # ------------------------------------------------------------------

    @classmethod
    def _get_semaphore(cls) -> asyncio.Semaphore:
        """获取全局并发控制Semaphore（懒加载）."""
        if cls._SEMAPHORE is None:
            cls._SEMAPHORE = asyncio.Semaphore(settings.LLM_MAX_CONCURRENT_CALLS)
        return cls._SEMAPHORE

    # ------------------------------------------------------------------
    # 重试逻辑
    # ------------------------------------------------------------------

    def _calculate_delay(self, attempt: int) -> float:
        """计算第 attempt 次重试的延迟时间（指数退避 + jitter）.

        Args:
            attempt: 当前重试次数（从1开始）。

        Returns:
            延迟秒数。
        """
        delay = self.base_delay * (self.backoff_multiplier ** (attempt - 1))
        delay = min(delay, self.max_delay)
        # 添加 ±20% 的 jitter，避免惊群效应
        jitter = delay * 0.2 * (2 * random.random() - 1)
        return max(0.0, delay + jitter)

    async def _call_with_retry(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        **kwargs: Any,
    ) -> LLMResponse:
        """带重试的单个模型调用.

        Args:
            model: 模型名称。
            system_prompt: 系统提示词。
            user_prompt: 用户提示词。
            **kwargs: 透传给 LLMClient.call()。

        Returns:
            LLMResponse

        Raises:
            LLMCallException: 所有重试均失败。
        """
        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug(
                    "LLM call attempt %d/%d, model=%s",
                    attempt,
                    self.max_retries,
                    model,
                )
                # 将重试次数注入 trace context（供 tracer 读取）
                set_trace_context(retry_count=attempt - 1)
                response = await self.client.call(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model=model,
                    **kwargs,
                )
                logger.debug(
                    "LLM call success, model=%s, tokens=%d",
                    model,
                    response.total_tokens,
                )
                return response
            except LLMCallException as e:
                last_error = e
                logger.warning(
                    "LLM call failed (attempt %d/%d), model=%s, error=%s",
                    attempt,
                    self.max_retries,
                    model,
                    e.message,
                )
                if attempt < self.max_retries:
                    delay = self._calculate_delay(attempt)
                    logger.debug("Retrying in %.2f seconds...", delay)
                    await asyncio.sleep(delay)

        raise last_error or LLMCallException(
            f"All {self.max_retries} retries failed for model {model}"
        )

    # ------------------------------------------------------------------
    # 对外接口：非流式调用
    # ------------------------------------------------------------------

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """生成LLM响应（含重试 + Fallback链）.

        这是业务层主要使用的接口。
        调用流程：
        1. 使用指定模型（或默认模型）尝试调用
        2. 失败则按配置重试
        3. 仍失败则按Fallback链切换备用模型
        4. 全局并发控制

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            model: 指定模型，默认使用 settings.DEFAULT_LLM_MODEL
            **kwargs: 其他参数（temperature, max_tokens, tools 等）

        Returns:
            LLMResponse
        """
        primary_model = model or settings.DEFAULT_LLM_MODEL

        # 构建完整的模型尝试链：主模型 + fallback_chain
        models_to_try = [primary_model]
        for fallback_model in self.fallback_chain:
            if fallback_model != primary_model and fallback_model not in models_to_try:
                models_to_try.append(fallback_model)

        last_error: Optional[Exception] = None

        async with self._get_semaphore():
            for m in models_to_try:
                try:
                    # 记录 fallback 信息（如果使用了非主模型）
                    if m != primary_model:
                        set_trace_context(fallback_model=m)
                    return await self._call_with_retry(
                        model=m,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        **kwargs,
                    )
                except LLMCallException as e:
                    last_error = e
                    logger.warning(
                        "Model %s exhausted all retries, trying next fallback...",
                        m,
                    )
                    continue

        raise last_error or LLMCallException(
            "All models in fallback chain failed"
        )

    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """生成JSON格式响应（自动设置 response_format）.

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            model: 指定模型
            **kwargs: 其他参数

        Returns:
            LLMResponse（content 应为合法JSON字符串）
        """
        return await self.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            response_format={"type": "json_object"},
            **kwargs,
        )

    # ------------------------------------------------------------------
    # 对外接口：流式调用
    # ------------------------------------------------------------------

    async def stream(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMStreamChunk]:
        """流式生成LLM响应.

        流式调用暂不支持自动Fallback（SSE连接建立后切换模型不现实），
        但支持指定fallback模型直接调用。

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            model: 指定模型
            **kwargs: 其他参数

        Yields:
            LLMStreamChunk
        """
        target_model = model or settings.DEFAULT_LLM_MODEL

        async with self._get_semaphore():
            async for chunk in self.client.stream_call(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=target_model,
                **kwargs,
            ):
                yield chunk

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """对话模式调用（直接传入messages列表）.

        Args:
            messages: OpenAI格式的消息列表
            model: 指定模型
            **kwargs: 其他参数

        Returns:
            LLMResponse
        """
        # 提取最后一条user消息作为user_prompt，其余拼接为system_prompt
        user_prompt = ""
        system_parts = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                system_parts.append(content)
            elif role == "user":
                user_prompt = content  # 取最后一条user
            elif role == "assistant":
                system_parts.append(f"Assistant: {content}")

        system_prompt = "\n\n".join(system_parts)
        return await self.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            **kwargs,
        )

    async def close(self) -> None:
        """关闭底层LLMClient."""
        await self.client.close()

    async def __aenter__(self) -> "LLMService":
        """异步上下文管理器入口."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文管理器出口."""
        await self.close()

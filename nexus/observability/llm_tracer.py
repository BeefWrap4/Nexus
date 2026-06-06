"""LLM 调用追踪系统.

Phase 6.1: 零侵入业务代码，使用 contextvars + 装饰器模式收集 LLM Trace。

设计原则：
1. 不修改 LLMClient.call() 的方法签名
2. 通过 contextvars 隐式传递 trace 上下文
3. 异步持久化（不阻塞主流程）
4. 支持跨 async 边界（Worker、Crew）
"""

from __future__ import annotations

import asyncio
import contextvars
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Optional
from uuid import UUID

from nexus.config import settings


# ---------------------------------------------------------------------------
# ContextVars: 隐式传递 trace 上下文
# ---------------------------------------------------------------------------

TRACE_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "trace_context", default={}
)


def set_trace_context(**kwargs: Any) -> contextvars.Token:
    """设置当前异步上下文中的 trace 元数据.

    用法（在 WorkflowEngine / AgentNodeExecutor / BaseAgent 中）：
        token = set_trace_context(run_id=run_id, node_id=node.id, tenant_id=...)
        try:
            result = await agent.execute(task)
        finally:
            TRACE_CONTEXT.reset(token)

    Returns:
        contextvars.Token: 用于重置上下文的 token。
    """
    current = TRACE_CONTEXT.get()
    new_ctx = {**current, **kwargs}
    return TRACE_CONTEXT.set(new_ctx)


def get_trace_context() -> dict[str, Any]:
    """获取当前 trace 上下文（只读）."""
    return dict(TRACE_CONTEXT.get())


# ---------------------------------------------------------------------------
# Trace 数据模型
# ---------------------------------------------------------------------------

@dataclass
class LLMTraceData:
    """单次 LLM 调用的追踪数据."""

    tenant_id: str = ""
    run_id: str | None = None
    node_id: str | None = None
    agent_id: str | None = None
    experiment_id: str | None = None

    model: str = ""
    provider: str = ""
    system_prompt: str = ""
    user_prompt: str = ""
    response_content: str = ""
    response_reasoning: str = ""
    tool_calls: list[dict] = field(default_factory=list)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    retry_count: int = 0
    fallback_model: str | None = None

    cache_hit: bool = False

    raw_response: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_db_dict(self) -> dict[str, Any]:
        """转换为数据库插入字典."""
        return {
            "tenant_id": self.tenant_id or "00000000-0000-0000-0000-000000000000",
            "run_id": self.run_id,
            "node_id": self.node_id,
            "agent_id": self.agent_id,
            "experiment_id": self.experiment_id,
            "model": self.model,
            "provider": self.provider,
            "system_prompt": self.system_prompt[:10000] if self.system_prompt else None,
            "user_prompt": self.user_prompt[:10000] if self.user_prompt else None,
            "response_content": self.response_content[:10000]
            if self.response_content
            else None,
            "response_reasoning": self.response_reasoning[:5000]
            if self.response_reasoning
            else None,
            "tool_calls": self.tool_calls if self.tool_calls else None,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "retry_count": self.retry_count,
            "fallback_model": self.fallback_model,
            "cache_hit": self.cache_hit,
            "raw_response": self.raw_response if self.raw_response else None,
        }


# ---------------------------------------------------------------------------
# Trace 收集上下文管理器
# ---------------------------------------------------------------------------

@asynccontextmanager
async def trace_llm_call(
    model: str,
    system_prompt: str,
    user_prompt: str,
    provider: str = "",
):
    """LLM 调用追踪上下文管理器.

    用法（在 LLMClient.call() 中包裹实际 HTTP 调用）：
        async with trace_llm_call(
            model="gpt-4o", system_prompt=sp, user_prompt=up, provider="openai"
        ) as tracer:
            response = await http_call(...)
            tracer.set_response(response)
    """
    ctx = TRACE_CONTEXT.get()
    start = perf_counter()

    trace_data = LLMTraceData(
        tenant_id=ctx.get("tenant_id", ""),
        run_id=ctx.get("run_id"),
        node_id=ctx.get("node_id"),
        agent_id=ctx.get("agent_id"),
        experiment_id=ctx.get("experiment_id"),
        model=model,
        provider=provider or ctx.get("provider", ""),
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )

    # 暴露一个可设置响应的接口
    class Tracer:
        def __init__(self, data: LLMTraceData):
            self.data = data

        def set_response(self, response: Any) -> None:
            """从 LLMResponse 提取数据."""
            from nexus.agent.llm_client import LLMResponse

            if isinstance(response, LLMResponse):
                self.data.response_content = response.content
                self.data.response_reasoning = response.reasoning_content
                self.data.tool_calls = response.tool_calls
                self.data.prompt_tokens = response.prompt_tokens
                self.data.completion_tokens = response.completion_tokens
                self.data.total_tokens = response.total_tokens
                self.data.cache_hit = getattr(response, "cache_hit", False)
                self.data.raw_response = response.raw if response.raw else {}
            elif isinstance(response, dict):
                self.data.response_content = response.get("content", "")
                self.data.raw_response = response

        def set_error(self, error: Exception) -> None:
            """记录错误信息."""
            self.data.response_content = f"[ERROR] {type(error).__name__}: {error}"

        def set_retry_info(self, retry_count: int, fallback_model: str | None = None) -> None:
            self.data.retry_count = retry_count
            self.data.fallback_model = fallback_model

    tracer = Tracer(trace_data)

    try:
        yield tracer
    finally:
        trace_data.latency_ms = int((perf_counter() - start) * 1000)
        # 修复 (S4-6): 用 safe_background_task 替代裸 asyncio.create_task
        # 之前 trace 持久化失败完全静默（fire-and-forget），现在会写 DLQ + 错误日志
        from nexus.utils.async_tasks import safe_background_task
        safe_background_task(
            _persist_trace(trace_data),
            task_name=f"llm_tracer_persist_{trace_data.run_id or 'unknown'}",
        )
        # 同步更新 Prometheus 指标
        _update_prometheus_metrics(trace_data)


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------

async def _persist_trace(trace_data: LLMTraceData) -> None:
    """将 trace 异步写入数据库."""
    try:
        from nexus.db.database import get_db_session
        from nexus.models.llm_trace import LLMCallTrace

        async with get_db_session() as session:
            trace = LLMCallTrace(**trace_data.to_db_dict())
            session.add(trace)
            # get_db_session 会自动 commit
    except Exception:
        # Trace 写入失败不应影响主流程
        import logging

        logging.getLogger(__name__).warning("Failed to persist LLM trace (DB unavailable)")


def _update_prometheus_metrics(trace_data: LLMTraceData) -> None:
    """更新 Prometheus 指标."""
    try:
        from nexus.observability.agent_metrics import (
            LLM_CALLS_TOTAL,
            LLM_CALL_LATENCY,
            LLM_TOKENS_TOTAL,
            record_llm_call,
            record_llm_retry,
        )

        status = "error" if trace_data.response_content.startswith("[ERROR]") else "success"
        tenant_id = trace_data.tenant_id or "default"
        model = trace_data.model or "unknown"
        provider = trace_data.provider or "unknown"

        # Cache metrics (deferred until metrics are uncommented)
        if trace_data.cache_hit:
            pass  # CACHE_HITS_TOTAL.labels(model=model, tenant_id=tenant_id).inc()
        else:
            pass  # CACHE_MISSES_TOTAL.labels(model=model, tenant_id=tenant_id).inc()

        # LLM metrics — only count actual LLM calls (cache miss or error)
        if not trace_data.cache_hit:
            # 使用新的详细指标函数
            record_llm_call(
                provider=provider,
                model=model,
                status=status,
                prompt_tokens=trace_data.prompt_tokens,
                completion_tokens=trace_data.completion_tokens,
                cost_usd=0.0,  # TODO: 从配置或API响应中计算成本
                latency_seconds=trace_data.latency_ms / 1000.0,
            )

            # 记录重试次数
            if trace_data.retry_count > 0:
                for _ in range(trace_data.retry_count):
                    record_llm_retry(provider=provider, model=model)

            # 保留旧指标以保持向后兼容
            LLM_CALLS_TOTAL.labels(model=model, status=status, tenant_id=tenant_id).inc()

            LLM_CALL_LATENCY.labels(model=model).observe(trace_data.latency_ms / 1000.0)

            if trace_data.prompt_tokens > 0:
                LLM_TOKENS_TOTAL.labels(
                    model=model,
                    token_type="prompt",
                ).inc(trace_data.prompt_tokens)

            if trace_data.completion_tokens > 0:
                LLM_TOKENS_TOTAL.labels(
                    model=model,
                    token_type="completion",
                ).inc(trace_data.completion_tokens)

    except Exception:
        import logging

        logging.getLogger(__name__).exception("Failed to update Prometheus metrics")

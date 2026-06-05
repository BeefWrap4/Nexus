"""NEXUS Prometheus 指标定义.

提供全局指标对象和 FastAPI 中间件，用于收集:
- API 请求数和耗时
- 工作流执行数和耗时
- 节点执行数
- HITL 待审批数
- ARQ 队列深度

使用方式:
    from nexus.observability.metrics import WORKFLOW_RUNS_TOTAL, record_workflow_run
    WORKFLOW_RUNS_TOTAL.labels(status="completed", tenant_id="xxx").inc()
"""

from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import Generator

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    CONTENT_TYPE_LATEST,
    generate_latest,
)
from fastapi import Request, Response
from fastapi.responses import PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware


# ---------------------------------------------------------------------------
# 全局指标定义
# ---------------------------------------------------------------------------

# 从 workflow_metrics 导入工作流相关指标（避免重复定义）
from nexus.observability.workflow_metrics import (
    WORKFLOW_DURATION as WORKFLOW_RUN_DURATION,
    WORKFLOW_RUNS_TOTAL,
    NODE_EXECUTIONS_TOTAL,
)

HITL_TASKS_PENDING = Gauge(
    "nexus_hitl_tasks_pending",
    "Number of pending HITL tasks",
    ["tenant_id"],
)

ARQ_JOBS_QUEUED = Gauge(
    "nexus_arq_jobs_queued",
    "Number of jobs queued in ARQ",
)

API_REQUESTS_TOTAL = Counter(
    "nexus_api_requests_total",
    "Total number of API requests",
    ["method", "endpoint", "status"],
)

API_REQUEST_DURATION = Histogram(
    "nexus_api_request_duration_seconds",
    "API request duration in seconds",
    ["endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# ---------------------------------------------------------------------------
# LLM 指标 (已在 llm_tracer.py 中定义，此处注释避免重复)
# ---------------------------------------------------------------------------
# LLM_CALLS_TOTAL = Counter(
#     "nexus_llm_calls_total",
#     "Total LLM calls",
#     ["model", "status", "tenant_id"],
# )
#
# LLM_LATENCY = Histogram(
#     "nexus_llm_latency_seconds",
#     "LLM call latency",
#     ["model"],
#     buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
# )
#
# LLM_TOKENS_TOTAL = Counter(
#     "nexus_llm_tokens_total",
#     "Total tokens consumed",
#     ["model", "token_type"],
# )

# ---------------------------------------------------------------------------
# Semantic Cache 指标 (已在 llm_tracer.py 中定义，此处注释避免重复)
# ---------------------------------------------------------------------------
# CACHE_HITS_TOTAL = Counter(
#     "nexus_cache_hits_total",
#     "Total semantic cache hits",
#     ["model", "tenant_id"],
# )
#
# CACHE_MISSES_TOTAL = Counter(
#     "nexus_cache_misses_total",
#     "Total semantic cache misses",
#     ["model", "tenant_id"],
# )
#
# CACHE_LATENCY = Histogram(
#     "nexus_cache_latency_seconds",
#     "Semantic cache lookup latency",
#     ["model"],
#     buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
# )


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------

@contextmanager
def record_workflow_run(status: str, tenant_id: str) -> Generator[None, None, None]:
    """记录工作流执行耗时和计数.

    使用:
        with record_workflow_run("completed", str(tenant_id)):
            result = await engine.execute(...)
    """
    start = perf_counter()
    try:
        yield
    finally:
        duration = perf_counter() - start
        WORKFLOW_RUNS_TOTAL.labels(status=status, tenant_id=tenant_id).inc()
        WORKFLOW_RUN_DURATION.labels(status=status).observe(duration)


def record_node_execution(node_type: str, status: str) -> None:
    """记录节点执行."""
    NODE_EXECUTIONS_TOTAL.labels(node_type=node_type, status=status).inc()


def set_hitl_pending(count: int, tenant_id: str) -> None:
    """设置待审批任务数."""
    HITL_TASKS_PENDING.labels(tenant_id=tenant_id).set(count)


# ---------------------------------------------------------------------------
# FastAPI 中间件
# ---------------------------------------------------------------------------

class PrometheusMiddleware(BaseHTTPMiddleware):
    """自动收集 API 请求指标.

    为每个请求记录:
    - nexus_api_requests_total{method, endpoint, status}
    - nexus_api_request_duration_seconds{endpoint}
    """

    async def dispatch(self, request: Request, call_next):
        # 跳过 /metrics 端点自身
        if request.url.path == "/metrics":
            return await call_next(request)

        start = perf_counter()
        response = await call_next(request)
        duration = perf_counter() - start

        method = request.method
        endpoint = request.url.path
        status = str(response.status_code)

        API_REQUESTS_TOTAL.labels(
            method=method, endpoint=endpoint, status=status
        ).inc()
        API_REQUEST_DURATION.labels(endpoint=endpoint).observe(duration)

        return response


# ---------------------------------------------------------------------------
# /metrics 端点
# ---------------------------------------------------------------------------

async def metrics_endpoint() -> Response:
    """Prometheus 抓取端点."""
    return PlainTextResponse(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )

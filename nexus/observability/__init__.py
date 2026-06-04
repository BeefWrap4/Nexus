"""NEXUS可观测性模块.

提供Prometheus指标采集、LLM调用追踪等功能。
"""

from nexus.observability.agent_metrics import (
    AGENT_DECISION_LATENCY,
    AGENT_EXECUTIONS_TOTAL,
    LLM_CALLS_TOTAL,
    LLM_COST_USD,
    LLM_TOKENS_TOTAL,
    LLM_CALL_LATENCY,
    LLM_CALL_FAILURES_TOTAL,
    LLM_RETRIES_TOTAL,
    record_agent_execution,
    record_llm_call,
    record_llm_retry,
)
from nexus.observability.llm_tracer import (
    LLMTraceData,
    get_trace_context,
    set_trace_context,
    trace_llm_call,
)
from nexus.observability.queue_metrics import (
    QUEUE_LENGTH,
    ACTIVE_WORKERS,
    TASK_PROCESSING_TIME,
    TASK_EXECUTIONS_TOTAL,
    TASK_FAILURES_TOTAL,
    TASK_RETRIES_TOTAL,
    DEAD_LETTER_JOBS,
    update_queue_length,
    update_active_workers,
    record_task_execution,
    record_task_retry,
    update_dead_letter_jobs,
)
from nexus.observability.workflow_metrics import (
    WORKFLOW_DURATION,
    WORKFLOW_RUNS_TOTAL,
    WORKFLOW_RUNNING,
    NODE_DURATION,
    NODE_EXECUTIONS_TOTAL,
    WORKFLOW_FAILURES_TOTAL,
    NODE_FAILURES_TOTAL,
    record_workflow_execution,
    update_workflow_running_count,
    record_node_execution,
)

__all__ = [
    # Workflow metrics
    "WORKFLOW_DURATION",
    "WORKFLOW_RUNS_TOTAL",
    "WORKFLOW_RUNNING",
    "NODE_DURATION",
    "NODE_EXECUTIONS_TOTAL",
    "WORKFLOW_FAILURES_TOTAL",
    "NODE_FAILURES_TOTAL",
    "record_workflow_execution",
    "update_workflow_running_count",
    "record_node_execution",
    # Agent metrics
    "AGENT_DECISION_LATENCY",
    "AGENT_EXECUTIONS_TOTAL",
    "LLM_CALLS_TOTAL",
    "LLM_COST_USD",
    "LLM_TOKENS_TOTAL",
    "LLM_CALL_LATENCY",
    "LLM_CALL_FAILURES_TOTAL",
    "LLM_RETRIES_TOTAL",
    "record_agent_execution",
    "record_llm_call",
    "record_llm_retry",
    # Queue metrics
    "QUEUE_LENGTH",
    "ACTIVE_WORKERS",
    "TASK_PROCESSING_TIME",
    "TASK_EXECUTIONS_TOTAL",
    "TASK_FAILURES_TOTAL",
    "TASK_RETRIES_TOTAL",
    "DEAD_LETTER_JOBS",
    "update_queue_length",
    "update_active_workers",
    "record_task_execution",
    "record_task_retry",
    "update_dead_letter_jobs",
    # LLM tracer
    "LLMTraceData",
    "get_trace_context",
    "set_trace_context",
    "trace_llm_call",
]

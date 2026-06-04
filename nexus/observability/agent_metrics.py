"""Agent系统Prometheus指标.

提供Agent决策延迟、LLM调用统计、Token使用等关键指标的采集。
"""

from prometheus_client import Counter, Histogram

# ============================================================================
# Agent决策指标
# ============================================================================

# Agent决策延迟直方图
AGENT_DECISION_LATENCY = Histogram(
    "nexus_agent_decision_latency_seconds",
    "Agent decision latency in seconds",
    ["agent_name", "status"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
)

# Agent执行总数
AGENT_EXECUTIONS_TOTAL = Counter(
    "nexus_agent_executions_total",
    "Total number of agent executions",
    ["agent_name", "status"],
)

# ============================================================================
# LLM调用指标
# ============================================================================

# LLM调用总数
LLM_CALLS_TOTAL = Counter(
    "nexus_llm_calls_total",
    "Total LLM API calls",
    ["provider", "model", "status"],
)

# LLM调用成本(USD)
LLM_COST_USD = Counter(
    "nexus_llm_cost_usd",
    "LLM API cost in USD",
    ["provider", "model"],
)

# LLM Token使用总量
LLM_TOKENS_TOTAL = Counter(
    "nexus_llm_tokens_total",
    "Total tokens used",
    ["type"],  # input/output/total
)

# LLM调用延迟直方图
LLM_CALL_LATENCY = Histogram(
    "nexus_llm_call_latency_seconds",
    "LLM API call latency in seconds",
    ["provider", "model"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# ============================================================================
# LLM错误指标
# ============================================================================

# LLM调用失败次数
LLM_CALL_FAILURES_TOTAL = Counter(
    "nexus_llm_call_failures_total",
    "Total LLM API call failures",
    ["provider", "model", "error_type"],
)

# LLM重试次数
LLM_RETRIES_TOTAL = Counter(
    "nexus_llm_retries_total",
    "Total LLM API call retries",
    ["provider", "model"],
)

# ============================================================================
# 辅助函数
# ============================================================================


def record_agent_execution(
    agent_name: str,
    status: str,
    duration_seconds: float,
) -> None:
    """记录Agent执行指标.

    Args:
        agent_name: Agent名称
        status: 执行状态 (success/failed/max_iterations_reached)
        duration_seconds: 执行时长(秒)
    """
    AGENT_DECISION_LATENCY.labels(
        agent_name=agent_name,
        status=status,
    ).observe(duration_seconds)

    AGENT_EXECUTIONS_TOTAL.labels(
        agent_name=agent_name,
        status=status,
    ).inc()


def record_llm_call(
    provider: str,
    model: str,
    status: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost_usd: float = 0.0,
    latency_seconds: float = 0.0,
) -> None:
    """记录LLM调用指标.

    Args:
        provider: LLM提供商 (openai/anthropic/deepseek/etc)
        model: 模型名称
        status: 调用状态 (success/error)
        prompt_tokens: 输入token数
        completion_tokens: 输出token数
        cost_usd: 调用成本(美元)
        latency_seconds: 调用延迟(秒)
    """
    LLM_CALLS_TOTAL.labels(
        provider=provider,
        model=model,
        status=status,
    ).inc()

    if prompt_tokens > 0:
        LLM_TOKENS_TOTAL.labels(type="input").inc(prompt_tokens)

    if completion_tokens > 0:
        LLM_TOKENS_TOTAL.labels(type="output").inc(completion_tokens)

    if prompt_tokens > 0 and completion_tokens > 0:
        LLM_TOKENS_TOTAL.labels(type="total").inc(
            prompt_tokens + completion_tokens
        )

    if cost_usd > 0:
        LLM_COST_USD.labels(provider=provider, model=model).inc(cost_usd)

    if latency_seconds > 0:
        LLM_CALL_LATENCY.labels(provider=provider, model=model).observe(
            latency_seconds
        )

    if status == "error":
        LLM_CALL_FAILURES_TOTAL.labels(
            provider=provider,
            model=model,
            error_type="api_error",
        ).inc()


def record_llm_retry(provider: str, model: str) -> None:
    """记录LLM重试次数.

    Args:
        provider: LLM提供商
        model: 模型名称
    """
    LLM_RETRIES_TOTAL.labels(provider=provider, model=model).inc()


__all__ = [
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
]

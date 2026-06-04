"""工作流执行Prometheus指标.

提供工作流执行延迟、成功率、并发数等关键指标的采集。
"""

from prometheus_client import Counter, Gauge, Histogram

# ============================================================================
# 工作流执行指标
# ============================================================================

# 工作流执行延迟直方图
WORKFLOW_DURATION = Histogram(
    "nexus_workflow_duration_seconds",
    "Workflow execution duration in seconds",
    ["status"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

# 工作流执行总数
WORKFLOW_RUNS_TOTAL = Counter(
    "nexus_workflow_runs_total",
    "Total number of workflow runs",
    ["tenant_id", "status"],
)

# 当前运行中的工作流数
WORKFLOW_RUNNING = Gauge(
    "nexus_workflow_running",
    "Number of currently running workflows",
    ["tenant_id"],
)

# ============================================================================
# 节点执行指标
# ============================================================================

# 节点执行延迟直方图
NODE_DURATION = Histogram(
    "nexus_node_duration_seconds",
    "Node execution duration in seconds",
    ["node_type", "status"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
)

# 节点执行总数
NODE_EXECUTIONS_TOTAL = Counter(
    "nexus_node_executions_total",
    "Total number of node executions",
    ["node_type", "status"],
)

# ============================================================================
# 工作流错误指标
# ============================================================================

# 工作流失败次数
WORKFLOW_FAILURES_TOTAL = Counter(
    "nexus_workflow_failures_total",
    "Total number of workflow failures",
    ["tenant_id", "error_type"],
)

# 节点失败次数
NODE_FAILURES_TOTAL = Counter(
    "nexus_node_failures_total",
    "Total number of node failures",
    ["node_type", "error_type"],
)

# ============================================================================
# 辅助函数
# ============================================================================


def record_workflow_execution(
    tenant_id: str,
    workflow_name: str,
    status: str,
    duration_seconds: float,
) -> None:
    """记录工作流执行指标.

    Args:
        tenant_id: 租户ID
        workflow_name: 工作流名称
        status: 执行状态 (succeeded/failed/cancelled)
        duration_seconds: 执行时长(秒)
    """
    WORKFLOW_DURATION.labels(
        tenant_id=tenant_id,
        workflow_name=workflow_name,
        status=status,
    ).observe(duration_seconds)

    WORKFLOW_RUNS_TOTAL.labels(
        tenant_id=tenant_id,
        status=status,
    ).inc()

    if status == "failed":
        WORKFLOW_FAILURES_TOTAL.labels(
            tenant_id=tenant_id,
            error_type="execution_error",
        ).inc()


def update_workflow_running_count(tenant_id: str, count: int) -> None:
    """更新当前运行中的工作流数量.

    Args:
        tenant_id: 租户ID
        count: 运行中的工作流数量
    """
    WORKFLOW_RUNNING.labels(tenant_id=tenant_id).set(count)


def record_node_execution(
    node_type: str,
    status: str,
    duration_seconds: float,
) -> None:
    """记录节点执行指标.

    Args:
        node_type: 节点类型 (agent/tool/condition/etc)
        status: 执行状态 (succeeded/failed)
        duration_seconds: 执行时长(秒)
    """
    NODE_DURATION.labels(node_type=node_type, status=status).observe(
        duration_seconds
    )

    NODE_EXECUTIONS_TOTAL.labels(node_type=node_type, status=status).inc()

    if status == "failed":
        NODE_FAILURES_TOTAL.labels(
            node_type=node_type,
            error_type="execution_error",
        ).inc()


__all__ = [
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
]

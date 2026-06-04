"""ARQ队列Prometheus指标.

提供队列长度、任务处理时间等关键指标的采集。
"""

from prometheus_client import Counter, Gauge, Histogram

# ============================================================================
# 队列状态指标
# ============================================================================

# ARQ队列长度
QUEUE_LENGTH = Gauge(
    "nexus_arq_queue_length",
    "ARQ job queue length",
)

# 活跃Worker数量
ACTIVE_WORKERS = Gauge(
    "nexus_arq_active_workers",
    "Number of active ARQ workers",
)

# ============================================================================
# 任务处理指标
# ============================================================================

# 任务处理时间直方图
TASK_PROCESSING_TIME = Histogram(
    "nexus_task_processing_time_seconds",
    "Task processing time in seconds",
    ["job_type"],
    buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0],
)

# 任务执行总数
TASK_EXECUTIONS_TOTAL = Counter(
    "nexus_task_executions_total",
    "Total number of task executions",
    ["job_type", "status"],
)

# ============================================================================
# 任务错误指标
# ============================================================================

# 任务失败次数
TASK_FAILURES_TOTAL = Counter(
    "nexus_task_failures_total",
    "Total number of task failures",
    ["job_type", "error_type"],
)

# 任务重试次数
TASK_RETRIES_TOTAL = Counter(
    "nexus_task_retries_total",
    "Total number of task retries",
    ["job_type"],
)

# 死信队列任务数
DEAD_LETTER_JOBS = Gauge(
    "nexus_dead_letter_jobs",
    "Number of jobs in dead letter queue",
)

# ============================================================================
# 辅助函数
# ============================================================================


def update_queue_length(length: int) -> None:
    """更新队列长度指标.

    Args:
        length: 当前队列长度
    """
    QUEUE_LENGTH.set(length)


def update_active_workers(count: int) -> None:
    """更新活跃Worker数量.

    Args:
        count: 活跃Worker数量
    """
    ACTIVE_WORKERS.set(count)


def record_task_execution(
    job_type: str,
    status: str,
    duration_seconds: float,
) -> None:
    """记录任务执行指标.

    Args:
        job_type: 任务类型 (workflow/scheduled/etc)
        status: 执行状态 (success/failed/retry)
        duration_seconds: 处理时长(秒)
    """
    TASK_PROCESSING_TIME.labels(job_type=job_type).observe(duration_seconds)

    TASK_EXECUTIONS_TOTAL.labels(job_type=job_type, status=status).inc()

    if status == "failed":
        TASK_FAILURES_TOTAL.labels(
            job_type=job_type,
            error_type="execution_error",
        ).inc()


def record_task_retry(job_type: str) -> None:
    """记录任务重试次数.

    Args:
        job_type: 任务类型
    """
    TASK_RETRIES_TOTAL.labels(job_type=job_type).inc()


def update_dead_letter_jobs(count: int) -> None:
    """更新死信队列任务数.

    Args:
        count: 死信队列中的任务数
    """
    DEAD_LETTER_JOBS.set(count)


__all__ = [
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
]

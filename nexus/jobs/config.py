"""ARQ Worker 配置.

定义 ARQ Worker 的 Redis 连接、并发设置和任务注册。

启动 Worker:
    arq nexus.jobs.config.WorkerSettings

或:
    python -m arq nexus.jobs.config.WorkerSettings
"""

from arq.connections import RedisSettings

from nexus.config import settings
from nexus.jobs.workflow import execute_workflow_job


class WorkerSettings:
    """ARQ Worker 配置类."""

    # Redis 连接
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)

    # 注册的任务函数
    functions = [execute_workflow_job]

    # 并发控制：同时处理的最大任务数
    max_jobs = settings.ARQ_WORKER_CONCURRENCY

    # 单个任务超时（秒）
    job_timeout = settings.ARQ_JOB_TIMEOUT

    # 任务最大重试次数
    max_tries = settings.ARQ_MAX_RETRIES

    # 任务结果保留时间（秒）
    keep_result = settings.ARQ_KEEP_RESULT

    # 健康检查端口（可选）
    health_check_port = 8080
    health_check_interval = 30

    # 优雅关闭等待时间
    max_shutdown_time = 30

    # Worker 启动/关闭钩子
    async def on_startup(self, ctx: dict) -> None:
        """Worker 启动时初始化."""
        import structlog

        logger = structlog.get_logger()
        logger.info(
            "arq_worker_started",
            worker_id=ctx.get("worker_id", "unknown"),
            max_jobs=self.max_jobs,
            redis=settings.REDIS_URL,
        )

    async def on_shutdown(self, ctx: dict) -> None:
        """Worker 关闭时清理."""
        import structlog

        logger = structlog.get_logger()
        logger.info(
            "arq_worker_shutdown",
            worker_id=ctx.get("worker_id", "unknown"),
            jobs_completed=ctx.get("jobs_completed", 0),
        )

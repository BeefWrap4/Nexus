"""ARQ Worker 配置.

定义 ARQ Worker 的 Redis 连接、并发设置和任务注册。

启动 Worker:
    arq nexus.jobs.config.WorkerSettings

或:
    python -m arq nexus.jobs.config.WorkerSettings
"""

from typing import Any

from arq import cron
from arq.connections import RedisSettings

from nexus.config import settings
from nexus.jobs.dlq import record_dead_letter_job
from nexus.jobs.scheduler import scheduled_workflow_trigger
from nexus.jobs.workflow import execute_workflow_job


async def recover_hitl_tasks() -> list[dict]:
    """恢复未完成的 HITL 任务.

    Worker 重启后从数据库扫描所有 pending 状态的 HITL 任务，
    并通过 EventBus 重新订阅，确保跨 Worker 响应机制正常工作。
    """
    import structlog

    from nexus.db.database import AsyncSessionLocal
    from nexus.models.hitl import HITLTask
    from sqlalchemy import select

    logger = structlog.get_logger()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(HITLTask).where(HITLTask.status.in_(["pending"]))
        )
        tasks = result.scalars().all()
        logger.info("hitl_recovery_scan_complete", pending_count=len(tasks))

        # 将 ORM 对象转为字典并重新订阅 EventBus
        recovered = []
        for t in tasks:
            task_dict = {
                "id": str(t.id),
                "wf_run_id": str(t.wf_run_id),
                "node_id": t.node_id,
                "task_type": t.task_type,
                "title": t.title,
                "description": t.description,
                "context": t.context,
                "assignee_id": str(t.assignee_id) if t.assignee_id else None,
                "status": t.status,
                "deadline": t.deadline.isoformat() if t.deadline else None,
                "responded_at": t.responded_at.isoformat() if t.responded_at else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            recovered.append(task_dict)
            logger.debug("hitl_task_recovered", task_id=task_dict["id"], status=t.status)

    return recovered


class WorkerSettings:
    """ARQ Worker 配置类."""

    # Redis 连接
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)

    # 注册的任务函数
    functions = [execute_workflow_job]

    # Cron 定时任务（每分钟扫描一次定时工作流）
    cron_jobs = [
        cron(
            scheduled_workflow_trigger,
            minute={0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
                  15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29,
                  30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44,
                  45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59},
            run_at_startup=False,
        ),
    ]

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

    # Worker 启动/关闭钩子 (ARQ 0.26+ 要求 staticmethod 签名)
    @staticmethod
    async def on_startup(ctx: dict) -> None:
        """Worker 启动时初始化."""
        import structlog

        logger = structlog.get_logger()
        logger.info(
            "arq_worker_started",
            worker_id=ctx.get("worker_id", "unknown"),
            redis=settings.REDIS_URL,
        )
        
        # 更新活跃Worker数量指标
        from nexus.observability.queue_metrics import update_active_workers
        update_active_workers(1)

        # HITL 恢复：扫描 pending 状态的 HITL 任务并重新订阅 EventBus
        try:
            recovered = await recover_hitl_tasks()
            logger.info("hitl_recovery_complete", recovered_count=len(recovered))
        except Exception:
            logger.warning("hitl_recovery_failed", exc_info=True)

    @staticmethod
    async def on_job_retry(ctx: dict[str, Any]) -> None:
        """任务重试时钩子.

        当重试次数达到上限时，将任务记录到死信队列。
        """
        job = ctx.get("job")
        if not job:
            return

        job_try = ctx.get("job_try", 0)
        max_tries = ctx.get("max_tries", 3)
        
        # 记录重试指标
        from nexus.observability.queue_metrics import record_task_retry
        record_task_retry(job_type="workflow")
        
        if job_try >= max_tries:
            exc = ctx.get("exception")
            if exc:
                await record_dead_letter_job(
                    ctx,
                    job_id=ctx.get("job_id", ""),
                    job_try=job_try,
                    exc=exc,
                )

    @staticmethod
    async def on_shutdown(ctx: dict) -> None:
        """Worker 关闭时清理."""
        import structlog

        logger = structlog.get_logger()
        logger.info(
            "arq_worker_shutdown",
            worker_id=ctx.get("worker_id", "unknown"),
            jobs_completed=ctx.get("jobs_completed", 0),
        )

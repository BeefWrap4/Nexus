"""死信队列（DLQ）处理模块.

当 ARQ 任务重试次数达到上限后，将失败任务记录到 DB 死信队列，
供运维人员排查和手动重试。
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from typing import Any

from nexus.db.database import get_db_session
from nexus.models.workflow import DeadLetterJob


async def record_dead_letter_job(
    ctx: dict[str, Any],
    job_id: str,
    job_try: int,
    exc: Exception,
) -> None:
    """记录失败任务到死信队列.

    由 WorkerSettings.on_job_retry 钩子调用，当 retry_count >= max_tries 时触发。

    Args:
        ctx: ARQ 上下文
        job_id: 任务ID
        job_try: 当前重试次数（从1开始）
        exc: 异常对象
    """
    import structlog

    logger = structlog.get_logger()

    # 获取任务参数（从 ARQ 上下文中）
    job = ctx.get("job")
    if not job:
        logger.warning("dlq_no_job_in_context", job_id=job_id)
        return

    try:
        # 解析任务参数
        args = job.args
        kwargs = job.kwargs if hasattr(job, "kwargs") else {}

        run_id = kwargs.get("run_id", "")
        tenant_id = kwargs.get("tenant_id", "")
        workflow_config = kwargs.get("workflow_config", {})

        async with get_db_session() as session:
            dlq_entry = DeadLetterJob(
                run_id=run_id,
                workflow_id=workflow_config.get("workflow_id") if isinstance(workflow_config, dict) else None,
                tenant_id=tenant_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
                traceback=traceback.format_exc(),
                payload={
                    "args": args,
                    "kwargs": kwargs,
                    "job_id": job_id,
                    "job_try": job_try,
                },
                retry_count=job_try,
                status="failed",
                failed_at=datetime.now(timezone.utc),
            )
            session.add(dlq_entry)

        logger.info(
            "dead_letter_job_recorded",
            job_id=job_id,
            run_id=run_id,
            error_type=type(exc).__name__,
            retry_count=job_try,
        )

    except Exception as record_exc:
        logger.error(
            "dead_letter_job_record_failed",
            job_id=job_id,
            error=str(record_exc),
        )


async def retry_dead_letter_job(
    job_id: str,
    arq_pool=None,
) -> dict[str, Any]:
    """手动重试死信队列中的任务.

    Args:
        job_id: 死信队列记录ID
        arq_pool: ARQ Redis 连接池

    Returns:
        {"success": bool, "message": str}
    """
    from uuid import UUID

    from nexus.jobs.pool import get_arq_pool

    if arq_pool is None:
        arq_pool = get_arq_pool()

    async with get_db_session() as session:
        from sqlalchemy import select

        stmt = select(DeadLetterJob).where(DeadLetterJob.id == UUID(job_id))
        result = await session.execute(stmt)
        dlq_job = result.scalar_one_or_none()

        if not dlq_job:
            return {"success": False, "message": "Dead letter job not found"}

        if dlq_job.status == "retried":
            return {"success": False, "message": "Job already retried"}

        payload = dlq_job.payload or {}
        kwargs = payload.get("kwargs", {})

        if arq_pool:
            await arq_pool.enqueue_job(
                "execute_workflow_job",
                **kwargs,
            )

        dlq_job.status = "retried"
        dlq_job.retried_at = datetime.now(timezone.utc)
        session.add(dlq_job)

    return {"success": True, "message": "Job requeued for retry"}


async def list_dead_letter_jobs(
    tenant_id: str | None = None,
    status: str = "failed",
    skip: int = 0,
    limit: int = 100,
) -> tuple[list[DeadLetterJob], int]:
    """列出错死信队列任务.

    Args:
        tenant_id: 租户过滤（None 返回所有）
        status: 状态过滤
        skip: 偏移量
        limit: 每页数量

    Returns:
        (任务列表, 总数)
    """
    from sqlalchemy import func, select

    async with get_db_session() as session:
        stmt = select(DeadLetterJob)
        if tenant_id:
            stmt = stmt.where(DeadLetterJob.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(DeadLetterJob.status == status)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_result = await session.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = stmt.order_by(DeadLetterJob.failed_at.desc()).offset(skip).limit(limit)
        result = await session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

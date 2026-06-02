"""ARQ Cron 定时任务调度器.

每分钟扫描所有配置了 schedule_cron 的 active 工作流，
检查是否到了触发时间，如果是则 enqueue 执行。

使用 Redis 记录每个工作流的最后触发时间，避免重复触发。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from croniter import croniter

from nexus.config import settings
from nexus.db.database import get_db_session
from nexus.models import Workflow
from nexus.services.run import RunService
from nexus.services.workflow import WorkflowService


async def scheduled_workflow_trigger(ctx: dict[str, Any]) -> dict[str, Any]:
    """ARQ Cron 任务：扫描并触发定时工作流.

    每分钟执行一次，检查所有 schedule_cron IS NOT NULL 且 status='active' 的工作流。
    """
    import structlog

    logger = structlog.get_logger()
    redis = ctx.get("redis")
    triggered = 0
    skipped = 0

    try:
        async with get_db_session() as session:
            from sqlalchemy import select

            stmt = select(Workflow).where(
                Workflow.schedule_cron.isnot(None),
                Workflow.status == "active",
            )
            result = await session.execute(stmt)
            scheduled_workflows = result.scalars().all()

            for wf in scheduled_workflows:
                run_id = await _maybe_trigger_workflow(
                    redis, wf, logger, session
                )
                if run_id:
                    triggered += 1
                else:
                    skipped += 1

        logger.info(
            "scheduled_workflow_scan_complete",
            triggered=triggered,
            skipped=skipped,
            total=len(scheduled_workflows),
        )

        return {"triggered": triggered, "skipped": skipped}

    except Exception as exc:
        logger.error("scheduled_workflow_scan_failed", error=str(exc))
        raise


async def _maybe_trigger_workflow(
    redis,
    wf: Workflow,
    logger,
    session,
) -> str | None:
    """检查并触发单个工作流（如果需要）.

    Returns:
        触发的 run_id，或 None（未到时间）
    """
    from nexus.jobs.pool import get_arq_pool

    cron_expr = wf.schedule_cron
    if not cron_expr:
        return None

    # 检查 Cron 表达式是否有效
    try:
        itr = croniter(cron_expr, datetime.now(timezone.utc))
    except Exception:
        logger.warning(
            "invalid_cron_expression",
            workflow_id=str(wf.id),
            cron=cron_expr,
        )
        return None

    # 获取上次触发时间（从 Redis）
    last_trigger_key = f"nexus:schedule:last_trigger:{wf.id}"
    last_trigger = None
    if redis:
        last_trigger_str = await redis.get(last_trigger_key)
        if last_trigger_str:
            last_trigger = datetime.fromisoformat(last_trigger_str)

    # 计算下次触发时间
    now = datetime.now(timezone.utc)
    next_trigger = itr.get_next(datetime)

    # 检查是否应该触发
    # 如果上次触发时间不存在，或下次触发时间已过
    should_trigger = False
    if last_trigger is None:
        # 从未触发过，检查当前是否在触发窗口内
        # （允许 60 秒内的延迟触发）
        prev_trigger = itr.get_prev(datetime)
        if prev_trigger and (now - prev_trigger).total_seconds() <= 60:
            should_trigger = True
    else:
        # 检查自上次触发后是否有新的触发点
        prev_trigger = itr.get_prev(datetime)
        while prev_trigger and prev_trigger > last_trigger:
            if (now - prev_trigger).total_seconds() <= 60:
                should_trigger = True
                break
            prev_trigger = itr.get_prev(datetime)

    if not should_trigger:
        return None

    # 触发工作流
    run_service = RunService()
    run = await run_service.trigger(
        session,
        workflow_id=wf.id,
        tenant_id=wf.tenant_id,
        trigger_payload={"scheduled": True, "triggered_at": now.isoformat()},
        trigger_type="schedule",
    )

    # 记录触发时间到 Redis
    if redis:
        await redis.set(last_trigger_key, now.isoformat())

    logger.info(
        "scheduled_workflow_triggered",
        workflow_id=str(wf.id),
        run_id=str(run.id),
        cron=cron_expr,
    )

    return str(run.id)

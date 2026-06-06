"""ARQ task entry point for workflow execution."""

from __future__ import annotations

import traceback
from time import perf_counter
from typing import Any
from uuid import UUID

import structlog

from nexus.db.database import get_db_session
from nexus.engine.builder import build_engine_and_executors
from nexus.engine.enums import RunStatus
from nexus.observability.metrics import WORKFLOW_RUN_DURATION, WORKFLOW_RUNS_TOTAL
from nexus.observability.queue_metrics import record_task_execution
from nexus.services.run import RunService


async def execute_workflow_job(
    ctx: dict[str, Any],
    run_id: str,
    workflow_config: dict[str, Any],
    trigger_payload: dict[str, Any],
    tenant_id: str,
) -> dict[str, Any]:
    """Execute a workflow inside an ARQ worker process."""
    logger = structlog.get_logger()
    redis = ctx.get("redis")
    run_service = RunService()

    logger.info(
        "workflow_job_started",
        run_id=run_id,
        tenant_id=tenant_id,
        worker_id=ctx.get("worker_id", "unknown"),
    )

    async with get_db_session() as session:
        run = await run_service.update_status(
            session,
            run_id=UUID(run_id),
            tenant_id=UUID(tenant_id),
            status=RunStatus.RUNNING.value,
        )
        if run is None:
            raise ValueError(f"Run {run_id} not found for tenant {tenant_id}")

    wf_def, engine, extras = build_engine_and_executors(
        config=workflow_config,
        redis_client=redis,
        register_extra=True,
    )
    event_bus = extras["event_bus"]
    state_manager = extras["state_manager"]

    await event_bus.publish(
        {
            "type": "run_started",
            "run_id": run_id,
            "tenant_id": tenant_id,
            "workflow_nodes": [n.id for n in wf_def.nodes],
        }
    )

    run_start = perf_counter()
    run_status = RunStatus.FAILED.value
    try:
        result = await engine.execute(wf_def, trigger_payload, run_id)
        run_status = result.status.value
        state = state_manager.get_state(run_id)

        await event_bus.publish(
            {
                "type": "run_completed",
                "run_id": run_id,
                "tenant_id": tenant_id,
                "status": result.status.value,
                "duration_ms": result.duration_ms,
                "node_states": {
                    nid: ns.value
                    for nid, ns in (state.node_states if state else {}).items()
                },
            }
        )

        async with get_db_session() as session:
            await run_service.update_status(
                session,
                run_id=UUID(run_id),
                tenant_id=UUID(tenant_id),
                status=result.status.value,
                result=result.output,
                state=state.to_dict() if state else {},
            )

        logger.info(
            "workflow_job_completed",
            run_id=run_id,
            status=result.status.value,
            duration_ms=result.duration_ms,
        )

        return {
            "run_id": run_id,
            "status": result.status.value,
            "duration_ms": result.duration_ms,
        }

    except Exception as exc:
        error_info = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }

        logger.error(
            "workflow_job_failed",
            run_id=run_id,
            error=error_info["message"],
            error_type=error_info["type"],
        )

        await event_bus.publish(
            {
                "type": "run_failed",
                "run_id": run_id,
                "tenant_id": tenant_id,
                "error": error_info,
            }
        )

        async with get_db_session() as session:
            await run_service.update_status(
                session,
                run_id=UUID(run_id),
                tenant_id=UUID(tenant_id),
                status=RunStatus.FAILED.value,
                result={"error": error_info},
            )

        raise
    finally:
        run_duration = perf_counter() - run_start
        WORKFLOW_RUNS_TOTAL.labels(status=run_status, tenant_id=tenant_id).inc()
        WORKFLOW_RUN_DURATION.labels(status=run_status).observe(run_duration)

        # 记录任务执行指标（队列级别）
        record_task_execution(
            job_type="workflow",
            status=run_status,
            duration_seconds=run_duration,
        )


async def resume_workflow_job(
    ctx: dict[str, Any],
    run_id: str,
    human_input: dict[str, Any],
    tenant_id: str,
) -> dict[str, Any]:
    """Resume a paused workflow run inside an ARQ worker process.

    Bug fix (S1-1): 之前 /api/v1/runs/{run_id}/resume 只改 status=RUNNING，
    从不调 execute()，导致 HITL pause→resume 在生产环境卡死。

    此任务:
    1. 从 DB 加载 WorkflowRun（拿 workflow_id + trigger_payload）
    2. 加载 Workflow.config（workflow 定义）
    3. 调 engine.resume(workflow_def, trigger_payload, run_id, human_input)
    4. engine.resume() 会从 checkpoint 恢复 state 并实际重跑
    """
    from uuid import UUID as _UUID

    from nexus.db.database import get_db_session
    from nexus.engine.builder import build_engine_and_executors
    from nexus.models.workflow import Workflow, WorkflowRun
    from sqlalchemy import select

    logger = structlog.get_logger()
    redis = ctx.get("redis")

    logger.info(
        "resume_workflow_job_started",
        run_id=run_id,
        tenant_id=tenant_id,
    )

    # 1. 加载 run 记录（拿 workflow_id, trigger_payload, config）
    async with get_db_session() as session:
        stmt = select(WorkflowRun).where(
            WorkflowRun.id == _UUID(run_id),
            WorkflowRun.tenant_id == _UUID(tenant_id),
        )
        result = await session.execute(stmt)
        run = result.scalar_one_or_none()
        if run is None:
            raise ValueError(f"Run {run_id} not found for tenant {tenant_id}")

        workflow_id = run.workflow_id
        trigger_payload = run.trigger_payload or {}

        # 2. 加载 workflow 定义
        wf_stmt = select(Workflow).where(Workflow.id == workflow_id)
        wf_result = await session.execute(wf_stmt)
        workflow = wf_result.scalar_one_or_none()
        if workflow is None:
            raise ValueError(f"Workflow {workflow_id} not found")

        workflow_config = workflow.config or {"nodes": [], "edges": []}

    # 3. 构建引擎（不 register_extra=True，HITL 节点已经执行过，不需要重启它）
    wf_def, engine, extras = build_engine_and_executors(
        config=workflow_config,
        redis_client=redis,
        register_extra=True,
    )

    # 4. 真正调 engine.resume() —— 这是修复点
    result = await engine.resume(
        run_id=run_id,
        human_input=human_input or {},
        workflow_def=wf_def,
        trigger_payload=trigger_payload,
    )

    logger.info(
        "resume_workflow_job_completed",
        run_id=run_id,
        status=result.status.value,
        duration_ms=result.duration_ms,
    )

    return {
        "run_id": run_id,
        "status": result.status.value,
        "duration_ms": result.duration_ms,
    }

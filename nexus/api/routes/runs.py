"""执行实例路由."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import get_db
from nexus.engine.enums import DLQJobStatus, RunStatus
from nexus.security.auth import get_current_user
from nexus.services.run import RunService
from nexus.services.node_run import NodeRunService

router = APIRouter()

run_service = RunService()
node_run_service = NodeRunService()


class RunResponse(BaseModel):
    id: str
    workflow_id: str
    status: str
    started_at: str
    completed_at: str | None

    model_config = ConfigDict(from_attributes=True)


def _to_response(run) -> RunResponse:
    return RunResponse(
        id=str(run.id),
        workflow_id=str(run.workflow_id),
        status=run.status,
        started_at=run.started_at.isoformat() if run.started_at else "",
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


@router.get("")
async def list_runs(
    limit: int = 10,
    skip: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取最近执行记录列表."""
    from nexus.models import WorkflowRun, Workflow
    from sqlalchemy import select, desc
    
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    
    # 查询runs并关联workflow名称
    stmt = (
        select(WorkflowRun, Workflow.name.label("workflow_name"))
        .outerjoin(Workflow, WorkflowRun.workflow_id == Workflow.id)
        .where(WorkflowRun.tenant_id == tenant_id)
        .order_by(desc(WorkflowRun.started_at))
        .offset(skip)
        .limit(limit)
    )
    
    result = await db.execute(stmt)
    runs_with_names = result.all()
    
    return [
        {
            "id": str(run.id),
            "workflow_id": str(run.workflow_id),
            "workflow_name": workflow_name or "Unknown",
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "duration_seconds": (
                (run.completed_at - run.started_at).total_seconds()
                if run.completed_at and run.started_at
                else None
            ),
        }
        for run, workflow_name in runs_with_names
    ]


@router.get("/{run_id}")
async def get_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取执行状态."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    run = await run_service.get(db, run_id, tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _to_response(run)


@router.post("/{run_id}/cancel")
async def cancel_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """取消执行."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    run = await run_service.update_status(db, run_id, tenant_id, RunStatus.CANCELLED.value)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return {"run_id": str(run.id), "status": run.status}


@router.post("/{run_id}/pause")
async def pause_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """暂停执行."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    run = await run_service.update_status(db, run_id, tenant_id, RunStatus.PAUSED.value)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return {"run_id": str(run.id), "status": run.status}


@router.post("/{run_id}/resume")
async def resume_run(
    request: Request,
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """恢复执行 — 真正把 resume_workflow_job 排进 ARQ 队列.

    Bug fix (S1-1): 之前这个端点只改 status=RUNNING，从不触发重跑，
    导致 HITL pause→resume 在生产环境永远卡住。修复：改 status 后立即
    通过 ARQ pool 把 resume_workflow_job 排进队列，Worker 进程会
    加载 workflow 定义 + checkpoint 并实际调 engine.resume()。
    """
    tenant_id = UUID(current_user.get("tenant_id", "default"))

    # 1. 验证 run 存在 + 改 status
    run = await run_service.update_status(db, run_id, tenant_id, RunStatus.RUNNING.value)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # 2. 解析 human_input（可选 body：{"approval": "approved", "notes": "..."}）
    human_input: dict = {}
    try:
        body = await request.json()
        if isinstance(body, dict):
            human_input = body
    except Exception:
        pass  # body 不是 JSON 或为空，使用空 dict

    # 3. 把 resume 任务排进 ARQ 队列
    try:
        from nexus.jobs.pool import get_arq_pool
        arq_pool = get_arq_pool()
        if arq_pool is None:
            raise HTTPException(
                status_code=503,
                detail="ARQ pool not initialized",
            )
        await arq_pool.enqueue_job(
            "resume_workflow_job",
            run_id=str(run_id),
            human_input=human_input,
            tenant_id=str(tenant_id),
        )
    except HTTPException:
        raise
    except Exception as e:
        # 队列入队失败也要返回错误，不要假装成功
        raise HTTPException(
            status_code=503,
            detail=f"Failed to enqueue resume job: {str(e)}",
        ) from e

    return {
        "run_id": str(run.id),
        "status": run.status,
        "resume_enqueued": True,
    }


@router.post("/{run_id}/retry")
async def retry_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """重试失败节点."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    run = await run_service.update_status(db, run_id, tenant_id, RunStatus.RUNNING.value)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return {"run_id": str(run.id), "status": run.status}


@router.get("/{run_id}/logs")
async def get_run_logs(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取执行日志."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    items, _ = await node_run_service.list_by_run(db, run_id, tenant_id=tenant_id)
    return [
        {
            "id": str(n.id),
            "node_id": n.node_id,
            "node_type": n.node_type,
            "status": n.status,
            "input": n.input_data,
            "output": n.output_data,
            "error": n.error,
            "started_at": n.started_at.isoformat() if n.started_at else None,
            "completed_at": n.completed_at.isoformat() if n.completed_at else None,
        }
        for n in items
    ]


@router.get("/{run_id}/artifacts")
async def get_run_artifacts(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取输出产物."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    return await run_service.list_artifacts_by_run(db, run_id, tenant_id)


# ---------------------------------------------------------------------------
# 死信队列（DLQ）端点
# ---------------------------------------------------------------------------

@router.get("/dlq")
async def list_dlq_jobs(
    status: str = DLQJobStatus.FAILED.value,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """列出死信队列中的失败任务."""
    from nexus.jobs.dlq import list_dead_letter_jobs

    tenant_id = current_user.get("tenant_id")
    items, total = await list_dead_letter_jobs(
        tenant_id=tenant_id,
        status=status,
        skip=skip,
        limit=limit,
    )

    return {
        "items": [
            {
                "id": str(j.id),
                "run_id": str(j.run_id),
                "workflow_id": str(j.workflow_id) if j.workflow_id else None,
                "error_type": j.error_type,
                "error_message": j.error_message,
                "retry_count": j.retry_count,
                "status": j.status,
                "failed_at": j.failed_at.isoformat() if j.failed_at else None,
            }
            for j in items
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.post("/dlq/{job_id}/retry")
async def retry_dlq_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """手动重试死信队列中的任务."""
    from nexus.jobs.dlq import retry_dead_letter_job

    tenant_id = current_user.get("tenant_id")
    result = await retry_dead_letter_job(str(job_id), tenant_id=tenant_id)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result

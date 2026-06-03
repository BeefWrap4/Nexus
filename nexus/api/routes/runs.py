"""执行实例路由."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import get_db
from nexus.security.auth import get_current_user
from nexus.services.run import RunService

router = APIRouter()

run_service = RunService()


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
    run = await run_service.update_status(db, run_id, tenant_id, "cancelled")
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
    run = await run_service.update_status(db, run_id, tenant_id, "paused")
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return {"run_id": str(run.id), "status": run.status}


@router.post("/{run_id}/resume")
async def resume_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """恢复执行."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    run = await run_service.update_status(db, run_id, tenant_id, "running")
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return {"run_id": str(run.id), "status": run.status}


@router.post("/{run_id}/retry")
async def retry_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """重试失败节点."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    run = await run_service.update_status(db, run_id, tenant_id, "running")
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
    items, _ = await run_service.list_node_runs(db, run_id)
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
    from sqlalchemy import select
    from nexus.models.audit import Artifact

    tenant_id = UUID(current_user.get("tenant_id", "default"))
    stmt = (
        select(Artifact)
        .where(Artifact.wf_run_id == run_id, Artifact.tenant_id == tenant_id)
        .order_by(Artifact.created_at)
    )
    result = await db.execute(stmt)
    artifacts = result.scalars().all()
    return [
        {
            "id": str(a.id),
            "name": a.name,
            "type": a.type,
            "mime_type": a.mime_type,
            "size_bytes": a.size_bytes,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in artifacts
    ]


# ---------------------------------------------------------------------------
# 死信队列（DLQ）端点
# ---------------------------------------------------------------------------

@router.get("/dlq")
async def list_dlq_jobs(
    status: str = "failed",
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

    result = await retry_dead_letter_job(str(job_id))

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result

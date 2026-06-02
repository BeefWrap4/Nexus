"""工作流路由.

对应WAT api/game_routes.py 升级:
- 从Game路由泛化为Workflow路由
- 增加版本管理
- 使用Service层替代硬编码mock
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import get_db
from nexus.exceptions import WorkflowNotFoundException
from nexus.security.auth import get_current_user
from nexus.services.workflow import WorkflowService, WorkflowVersionService

router = APIRouter()

workflow_service = WorkflowService()
version_service = WorkflowVersionService()


# Pydantic模型
class WorkflowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    config: dict = Field(default_factory=dict)
    variables: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[dict] = None
    variables: Optional[dict] = None
    tags: Optional[list[str]] = None
    status: Optional[str] = None


class WorkflowResponse(BaseModel):
    id: str
    name: str
    description: str
    status: str
    current_version: int
    run_count: int
    created_at: str

    class Config:
        from_attributes = True


class WorkflowRunRequest(BaseModel):
    trigger_payload: dict = Field(default_factory=dict)
    version: Optional[int] = None


def _to_response(wf) -> WorkflowResponse:
    return WorkflowResponse(
        id=str(wf.id),
        name=wf.name,
        description=wf.description or "",
        status=wf.status,
        current_version=wf.current_version or 1,
        run_count=wf.run_count or 0,
        created_at=wf.created_at.isoformat() if wf.created_at else "",
    )


@router.get("/", response_model=list[WorkflowResponse])
async def list_workflows(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """列出工作流."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    filters = {"status": status} if status else None
    items, _ = await workflow_service.list(db, tenant_id, skip, limit, filters)
    return [_to_response(w) for w in items]


@router.post("/", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    data: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """创建工作流."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    user_id = UUID(current_user.get("id"))
    wf = await workflow_service.create(
        db,
        data={
            "name": data.name,
            "description": data.description,
            "config": data.config,
            "variables": data.variables,
            "tags": data.tags,
        },
        tenant_id=tenant_id,
        user_id=user_id,
    )
    await db.commit()
    return _to_response(wf)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取工作流详情."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    wf = await workflow_service.get(db, workflow_id, tenant_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _to_response(wf)


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: UUID,
    data: WorkflowUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """更新工作流."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    wf = await workflow_service.update(
        db,
        workflow_id,
        data=data.model_dump(exclude_unset=True),
        tenant_id=tenant_id,
    )
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await db.commit()
    return _to_response(wf)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除工作流."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    ok = await workflow_service.delete(db, workflow_id, tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await db.commit()
    return None


@router.post("/{workflow_id}/runs")
async def trigger_workflow_run(
    workflow_id: UUID,
    data: WorkflowRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """触发工作流执行."""
    from nexus.services.run import RunService

    tenant_id = UUID(current_user.get("tenant_id", "default"))
    run_service = RunService()
    run = await run_service.trigger(
        db,
        workflow_id=workflow_id,
        tenant_id=tenant_id,
        trigger_payload=data.trigger_payload,
        trigger_type="api",
    )
    await db.commit()
    return {
        "run_id": str(run.id),
        "workflow_id": str(workflow_id),
        "status": run.status,
        "message": "Workflow run triggered successfully",
    }


@router.get("/{workflow_id}/runs")
async def list_workflow_runs(
    workflow_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """列出工作流执行记录."""
    from nexus.services.run import RunService

    tenant_id = UUID(current_user.get("tenant_id", "default"))
    run_service = RunService()
    items, _ = await run_service.list_by_workflow(db, workflow_id, tenant_id, skip, limit)
    return [
        {
            "id": str(r.id),
            "status": r.status,
            "trigger_type": r.trigger_type,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in items
    ]


@router.post("/{workflow_id}/versions")
async def create_version(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """创建工作流新版本."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    user_id = UUID(current_user.get("id"))
    wf = await workflow_service.get(db, workflow_id, tenant_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    ver = await version_service.create(
        db,
        data={
            "workflow_id": workflow_id,
            "config": wf.config,
        },
        tenant_id=tenant_id,
        user_id=user_id,
    )
    await db.commit()
    return {"version": ver.version, "workflow_id": str(workflow_id)}


@router.get("/{workflow_id}/versions")
async def list_versions(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """列出版本历史."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    items, _ = await version_service.list_by_workflow(db, workflow_id, tenant_id)
    return [
        {
            "id": str(v.id),
            "version": v.version,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in items
    ]


@router.post("/{workflow_id}/clone")
async def clone_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """克隆工作流."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    user_id = UUID(current_user.get("id"))
    wf = await workflow_service.get(db, workflow_id, tenant_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    new_wf = await workflow_service.create(
        db,
        data={
            "name": f"{wf.name} (Copy)",
            "description": wf.description,
            "config": wf.config,
            "variables": wf.variables,
            "tags": wf.tags,
        },
        tenant_id=tenant_id,
        user_id=user_id,
    )
    await db.commit()
    return {"new_workflow_id": str(new_wf.id), "source": str(workflow_id)}


# ---------------------------------------------------------------------------
# 定时任务调度
# ---------------------------------------------------------------------------

class ScheduleRequest(BaseModel):
    """定时任务请求."""

    cron: str = Field(..., min_length=5, max_length=100, description="Cron 表达式，如 '0 9 * * *'")


@router.post("/{workflow_id}/schedule")
async def schedule_workflow(
    workflow_id: UUID,
    data: ScheduleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """设置工作流定时任务.

    Cron 表达式格式（标准 5 字段）:
        分 时 日 月 周
        0  9  *  *  *   → 每天 9:00
        */5 * * * *     → 每 5 分钟
    """
    from croniter import croniter

    # 验证 Cron 表达式
    try:
        croniter(data.cron)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid cron expression: {data.cron}")

    tenant_id = UUID(current_user.get("tenant_id", "default"))
    wf = await workflow_service.get(db, workflow_id, tenant_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    wf.schedule_cron = data.cron
    # 设置定时任务后自动激活工作流
    if wf.status == "draft":
        wf.status = "active"

    db.add(wf)
    await db.commit()

    return {
        "workflow_id": str(workflow_id),
        "schedule_cron": data.cron,
        "status": wf.status,
        "message": "Workflow scheduled successfully",
    }


@router.delete("/{workflow_id}/schedule")
async def unschedule_workflow(
    workflow_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """取消工作流定时任务."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    wf = await workflow_service.get(db, workflow_id, tenant_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    old_cron = wf.schedule_cron
    wf.schedule_cron = None
    db.add(wf)
    await db.commit()

    return {
        "workflow_id": str(workflow_id),
        "previous_cron": old_cron,
        "message": "Workflow unscheduled successfully",
    }

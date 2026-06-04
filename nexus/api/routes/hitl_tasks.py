"""HITL审批任务路由."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import get_db
from nexus.engine.enums import HITLStatus
from nexus.engine.event_bus import EventBus
from nexus.security.auth import get_current_user
from nexus.services.hitl import HITLService

router = APIRouter()

hitl_service = HITLService()


class HITLResponseRequest(BaseModel):
    approved: bool = True
    selection: str | None = None
    input_data: dict | None = None
    correction: dict | None = None
    notes: str = ""


class HITLTaskResponse(BaseModel):
    id: str
    run_id: str
    node_id: str
    task_type: str
    title: str
    status: str
    created_at: str

    model_config = ConfigDict(from_attributes=True)


def _to_response(task) -> HITLTaskResponse:
    return HITLTaskResponse(
        id=str(task.id),
        run_id=str(task.wf_run_id),
        node_id=task.node_id,
        task_type=task.task_type,
        title=task.title,
        status=task.status,
        created_at=task.created_at.isoformat() if task.created_at else "",
    )


@router.get("/tasks")
async def list_hitl_tasks(
    status: str = "pending",
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """列出审批任务."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    filters = {"status": status}
    items, _ = await hitl_service.list(db, tenant_id, filters=filters)
    return [_to_response(t) for t in items]


@router.get("/tasks/{task_id}")
async def get_hitl_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取任务详情."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    task = await hitl_service.get(db, task_id, tenant_id)
    if not task:
        raise HTTPException(status_code=404, detail="HITL task not found")
    return _to_response(task)


@router.post("/tasks/{task_id}/respond")
async def respond_to_hitl_task(
    task_id: UUID,
    data: HITLResponseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """提交审批响应.

    响应后通过 EventBus 广播 hitl_response 事件，
    让执行工作流的 Worker 收到并恢复执行。
    """
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    user_id = current_user.get("id")
    response_payload = {
        "approved": data.approved,
        "selection": data.selection,
        "input_data": data.input_data,
        "correction": data.correction,
        "notes": data.notes,
        "status": HITLStatus.APPROVED.value if data.approved else HITLStatus.REJECTED.value,
    }
    task = await hitl_service.respond(
        db,
        task_id=task_id,
        tenant_id=tenant_id,
        response=response_payload,
        assignee_id=UUID(user_id) if user_id else None,
    )
    if not task:
        raise HTTPException(status_code=404, detail="HITL task not found")


    # 广播 HITL 响应事件（跨进程：Worker 通过 Redis Pub/Sub 收到）
    event_bus = None
    if hasattr(request.app.state, "event_bus"):
        event_bus = request.app.state.event_bus
    else:
        event_bus = EventBus()

    try:
        await event_bus.publish(
            {
                "type": "hitl_response",
                "task_id": str(task_id),
                "run_id": str(task.wf_run_id),
                "node_id": task.node_id,
                "response": response_payload,
                "tenant_id": str(tenant_id),
            }
        )
    except Exception as exc:
        # 事件广播失败不应阻塞 API 响应，但需记录日志
        import logging
        logger = logging.getLogger(__name__)
        logger.warning("Failed to broadcast HITL response event: %s", exc)

    return {
        "task_id": str(task.id),
        "status": task.status,
        "responded_by": user_id,
    }


@router.get("/tasks/pending/count")
async def get_pending_count(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取待审批数量."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    items, total = await hitl_service.list_pending(db, tenant_id)
    return {"count": total}

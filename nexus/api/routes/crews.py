"""Crew 团队路由.

Phase 10: 多 Agent 协作增强
- Crew CRUD
- Crew 执行触发
- Crew 执行历史
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import get_db
from nexus.models.crew import CrewRun
from nexus.security.auth import get_current_user
from nexus.services.crew import CrewService, CrewRunService
from nexus.services.crew_execution import CrewExecutionService

router = APIRouter()

crew_service = CrewService()
crew_run_service = CrewRunService()
crew_execution_service = CrewExecutionService()


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------

class CrewAgentRef(BaseModel):
    """Crew 中引用的 Agent."""

    agent_id: str
    role_in_crew: str = "worker"  # manager | worker
    order_index: int = 0


class CrewCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    mode: str = "hierarchical"  # hierarchical | sequential | parallel
    config: dict = Field(default_factory=dict)
    agent_ids: list[CrewAgentRef] = Field(default_factory=list)


class CrewUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    mode: Optional[str] = None
    config: Optional[dict] = None
    agent_ids: Optional[list[CrewAgentRef]] = None


class CrewResponse(BaseModel):
    id: str
    name: str
    description: str
    mode: str
    config: dict
    agents: list[dict]
    created_at: str
    updated_at: str


class CrewRunRequest(BaseModel):
    task_description: str = Field(..., min_length=1)
    context: dict = Field(default_factory=dict)


class CrewRunResponse(BaseModel):
    id: str
    crew_id: str
    status: str
    input_task: str
    output: str
    worker_results: list[dict]
    duration_ms: int
    started_at: str
    completed_at: Optional[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_crew_response(crew_data: dict) -> CrewResponse:
    return CrewResponse(
        id=crew_data["id"],
        name=crew_data["name"],
        description=crew_data.get("description", ""),
        mode=crew_data["mode"],
        config=crew_data.get("config", {}),
        agents=crew_data.get("agents", []),
        created_at=crew_data.get("created_at", ""),
        updated_at=crew_data.get("updated_at", ""),
    )


def _to_run_response(run: CrewRun) -> CrewRunResponse:
    return CrewRunResponse(
        id=str(run.id),
        crew_id=str(run.crew_id),
        status=run.status,
        input_task=run.input_task or "",
        output=run.output or "",
        worker_results=run.worker_results or [],
        duration_ms=run.duration_ms or 0,
        started_at=run.started_at.isoformat() if run.started_at else "",
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


# ---------------------------------------------------------------------------
# CRUD Endpoints
# ---------------------------------------------------------------------------

@router.get("/")
async def list_crews(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """列出 Crew 团队."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    items, _ = await crew_service.list(db, tenant_id, skip, limit)

    results = []
    for crew in items:
        crew_data = await crew_service.get_with_agents(db, crew.id, tenant_id)
        if crew_data:
            results.append(_to_crew_response(crew_data))
    return results


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_crew(
    data: CrewCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """创建 Crew 团队."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))

    crew = await crew_service.create(
        db,
        data={
            "name": data.name,
            "description": data.description,
            "mode": data.mode,
            "config": data.config,
            "agent_ids": [
                {
                    "agent_id": UUID(a.agent_id),
                    "role_in_crew": a.role_in_crew,
                    "order_index": a.order_index,
                }
                for a in data.agent_ids
            ],
        },
        tenant_id=tenant_id,
    )

    crew_data = await crew_service.get_with_agents(db, crew.id, tenant_id)
    return _to_crew_response(crew_data)


@router.get("/{crew_id}")
async def get_crew(
    crew_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取 Crew 详情."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    crew_data = await crew_service.get_with_agents(db, crew_id, tenant_id)
    if not crew_data:
        raise HTTPException(status_code=404, detail="Crew not found")
    return _to_crew_response(crew_data)


@router.put("/{crew_id}")
async def update_crew(
    crew_id: UUID,
    data: CrewUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """更新 Crew."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))

    update_data = data.model_dump(exclude_unset=True)
    if "agent_ids" in update_data:
        update_data["agent_ids"] = [
            {
                "agent_id": UUID(a["agent_id"]),
                "role_in_crew": a.get("role_in_crew", "worker"),
                "order_index": a.get("order_index", 0),
            }
            for a in update_data["agent_ids"]
        ]

    crew = await crew_service.update(db, crew_id, update_data, tenant_id)
    if not crew:
        raise HTTPException(status_code=404, detail="Crew not found")

    crew_data = await crew_service.get_with_agents(db, crew.id, tenant_id)
    return _to_crew_response(crew_data)


@router.delete("/{crew_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_crew(
    crew_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除 Crew."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    ok = await crew_service.delete(db, crew_id, tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Crew not found")
    return None


# ---------------------------------------------------------------------------
# Execution Endpoints
# ---------------------------------------------------------------------------

@router.post("/{crew_id}/run")
async def run_crew(
    crew_id: UUID,
    req: CrewRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """触发 Crew 执行."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))

    try:
        result = await crew_execution_service.run(
            db,
            crew_id=crew_id,
            tenant_id=tenant_id,
            task_description=req.task_description,
            context=req.context,
        )
    except ValueError as exc:
        error_msg = str(exc).lower()
        if "not found" in error_msg:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Crew execution failed: {exc}"
        ) from exc

    return {
        "run_id": result["run_id"],
        "status": result["status"],
        "output": result["output"],
        "worker_results": result["worker_results"],
        "duration_ms": result["duration_ms"],
    }


@router.get("/{crew_id}/runs")
async def list_crew_runs(
    crew_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取 Crew 执行历史."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    items, _ = await crew_run_service.list_by_crew(db, crew_id, tenant_id, skip, limit)
    return [_to_run_response(r) for r in items]


@router.get("/runs/{run_id}")
async def get_crew_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取 Crew 执行详情."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    run = await crew_run_service.get(db, run_id, tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="Crew run not found")
    return _to_run_response(run)

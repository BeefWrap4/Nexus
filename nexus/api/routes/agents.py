"""Agent路由."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import get_db
from nexus.security.auth import get_current_user
from nexus.services.agent import AgentService

router = APIRouter()

agent_service = AgentService()


class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    role: str = ""
    goal: str = ""
    backstory: str = ""
    llm_config: dict = Field(default_factory=dict)
    system_prompt: str = ""
    tools: list[str] = Field(default_factory=list)
    max_iterations: int = 10


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    goal: Optional[str] = None
    backstory: Optional[str] = None
    llm_config: Optional[dict] = None
    system_prompt: Optional[str] = None
    tools: Optional[list[str]] = None
    max_iterations: Optional[int] = None


class AgentResponse(BaseModel):
    id: str
    name: str
    role: str
    goal: str
    llm_config: dict
    created_at: str

    model_config = ConfigDict(from_attributes=True)


def _to_response(agent) -> AgentResponse:
    return AgentResponse(
        id=str(agent.id),
        name=agent.name,
        role=agent.role or "",
        goal=agent.goal or "",
        llm_config=agent.model_config or {},
        created_at=agent.created_at.isoformat() if agent.created_at else "",
    )


@router.get("/")
async def list_agents(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """列出Agent."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    items, _ = await agent_service.list(db, tenant_id, skip, limit)
    return [_to_response(a) for a in items]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_agent(
    data: AgentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """创建Agent."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    agent = await agent_service.create(
        db,
        data={
            "name": data.name,
            "role": data.role,
            "goal": data.goal,
            "backstory": data.backstory,
            "model_config": data.llm_config,
            "system_prompt": data.system_prompt,
            "tools": data.tools,
            "max_iterations": data.max_iterations,
        },
        tenant_id=tenant_id,
    )

    return _to_response(agent)


@router.get("/{agent_id}")
async def get_agent(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取Agent."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    agent = await agent_service.get(db, agent_id, tenant_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _to_response(agent)


@router.put("/{agent_id}")
async def update_agent(
    agent_id: UUID,
    data: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """更新Agent."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    agent = await agent_service.update(
        db,
        agent_id,
        data=data.model_dump(exclude_unset=True),
        tenant_id=tenant_id,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return _to_response(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除Agent."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    ok = await agent_service.delete(db, agent_id, tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Agent not found")

    return None

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

from nexus.agent.crew import Crew, CrewConfig, CrewMode
from nexus.agent.base import AgentConfig, BaseAgent, Task
from nexus.agent.llm_client import LLMClient
from nexus.config import settings
from nexus.db.database import get_db
from nexus.models.crew import CrewRun
from nexus.security.auth import get_current_user
from nexus.services.crew import CrewService, CrewRunService

router = APIRouter()

crew_service = CrewService()
crew_run_service = CrewRunService()


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


def _create_llm_client(model_config: dict) -> LLMClient:
    """根据模型配置创建 LLMClient."""
    import os

    provider = model_config.get("provider", settings.DEFAULT_LLM_PROVIDER)

    provider_base_urls = {
        "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
        "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
        "siliconflow": ("https://api.siliconflow.cn/v1", "SILICONFLOW_API_KEY"),
        "dashscope": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
        "zhipu": ("https://open.bigmodel.cn/api/paas/v4", "ZHIPU_API_KEY"),
    }

    if provider in provider_base_urls:
        direct_url, env_key = provider_base_urls[provider]
        api_key = os.environ.get(env_key)
        if api_key:
            base_url = direct_url
        else:
            base_url = settings.LITELLM_PROXY_URL
            api_key = settings.LITELLM_API_KEY
    else:
        base_url = settings.LITELLM_PROXY_URL
        api_key = settings.LITELLM_API_KEY

    return LLMClient(proxy_url=base_url, api_key=api_key)


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
    await db.commit()

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
    await db.commit()

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
    await db.commit()
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

    # 1. 加载 Crew 配置
    crew_data = await crew_service.get_with_agents(db, crew_id, tenant_id)
    if not crew_data:
        raise HTTPException(status_code=404, detail="Crew not found")

    # 2. 创建执行记录
    crew_run = await crew_run_service.create(
        db, crew_id, req.task_description, tenant_id
    )
    await db.commit()

    # 3. 构建 Agent 实例
    from nexus.models.agent import Agent as AgentModel
    from nexus.db.database import AsyncSessionLocal

    workers = []
    manager = None

    async with AsyncSessionLocal() as agent_session:
        from sqlalchemy import select

        for agent_ref in crew_data["agents"]:
            stmt = select(AgentModel).where(AgentModel.id == UUID(agent_ref["id"]))
            result = await agent_session.execute(stmt)
            agent_model = result.scalar_one_or_none()
            if not agent_model:
                continue

            agent_config = AgentConfig(
                name=agent_model.name,
                role=agent_model.role or "",
                goal=agent_model.goal or "",
                backstory=agent_model.backstory or "",
                system_prompt=agent_model.system_prompt or "",
                provider=agent_model.model_config.get("provider", settings.DEFAULT_LLM_PROVIDER),
                model=agent_model.model_config.get("model", settings.DEFAULT_LLM_MODEL),
                temperature=agent_model.model_config.get("temperature", settings.DEFAULT_LLM_TEMPERATURE),
                max_tokens=agent_model.model_config.get("max_tokens", settings.DEFAULT_LLM_MAX_TOKENS),
                max_iterations=agent_model.max_iterations or settings.DEFAULT_MAX_ITERATIONS,
                tools=agent_model.tools or [],
            )

            llm_client = _create_llm_client(agent_model.model_config)
            base_agent = BaseAgent(
                config=agent_config,
                llm_client=llm_client,
            )

            if agent_ref["role_in_crew"] == "manager":
                manager = base_agent
            else:
                workers.append(base_agent)

    if not manager and workers:
        manager = workers.pop(0)

    if not manager:
        raise HTTPException(status_code=400, detail="Crew has no valid agents")

    # 4. 构建 Crew 配置并执行
    config = CrewConfig(
        mode=CrewMode(crew_data["mode"]),
        max_workers=crew_data.get("config", {}).get("max_workers", 5),
        shared_context_enabled=crew_data.get("config", {}).get("shared_context_enabled", True),
        auto_delegate=crew_data.get("config", {}).get("auto_delegate", True),
    )

    crew = Crew(
        manager=manager,
        workers=workers,
        config=config,
        crew_id=str(crew_id),
    )

    import asyncio
    from time import perf_counter

    start = perf_counter()
    try:
        result = await crew.execute(
            task_description=req.task_description,
            context=req.context,
        )
        duration_ms = int((perf_counter() - start) * 1000)

        # 更新执行记录
        worker_results = [
            {
                "worker_name": w.worker_name,
                "output": w.output,
                "success": w.success,
                "error": w.error,
            }
            for w in result.worker_results
        ]

        async with AsyncSessionLocal() as update_session:
            await crew_run_service.update_status(
                update_session,
                crew_run.id,
                status="completed",
                output=result.output,
                worker_results=worker_results,
                duration_ms=duration_ms,
            )
            await update_session.commit()

        return {
            "run_id": str(crew_run.id),
            "status": "completed",
            "output": result.output,
            "worker_results": worker_results,
            "duration_ms": duration_ms,
        }

    except Exception as e:
        duration_ms = int((perf_counter() - start) * 1000)

        async with AsyncSessionLocal() as update_session:
            await crew_run_service.update_status(
                update_session,
                crew_run.id,
                status="failed",
                output="",
                worker_results=[{"error": str(e)}],
                duration_ms=duration_ms,
            )
            await update_session.commit()

        raise HTTPException(status_code=500, detail=f"Crew execution failed: {str(e)}")


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

"""Eval 评估框架 API.

Phase 6.5: Eval CRUD + 执行 + 结果对比。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.agent.base import AgentConfig
from nexus.db.database import get_db
from nexus.eval.runner import EvalRunner
from nexus.models.eval import EvalRun
from nexus.security.auth import get_current_user

router = APIRouter()


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------

class EvalRunCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    eval_type: str = "exact_match"  # llm_judge / exact_match / regex / contains
    dataset: list[dict[str, Any]] = Field(default_factory=list)
    agent_config: dict[str, Any] | None = None  # 可选的 Agent 配置


class EvalRunOut(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    eval_type: str
    status: str
    dataset: list[dict] | None = None
    results: dict[str, Any] | None = None
    created_at: Any | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@router.post("/evals", response_model=EvalRunOut)
async def create_eval_run(
    data: EvalRunCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """创建评估运行."""
    tenant_id = getattr(current_user, "tenant_id", None)

    eval_run = EvalRun(
        tenant_id=tenant_id,
        name=data.name,
        eval_type=data.eval_type,
        dataset=data.dataset,
        status="pending",
    )
    db.add(eval_run)
    await db.commit()  # TODO: extract to EvalService
    await db.refresh(eval_run)
    return eval_run


@router.get("/evals", response_model=list[EvalRunOut])
async def list_eval_runs(
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """列出评估运行."""
    tenant_id = getattr(current_user, "tenant_id", None)
    stmt = select(EvalRun).order_by(desc(EvalRun.created_at))
    if tenant_id:
        stmt = stmt.where(EvalRun.tenant_id == tenant_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/evals/{eval_id}", response_model=EvalRunOut)
async def get_eval_run(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """获取评估运行详情（含结果）."""
    result = await db.execute(
        select(EvalRun).where(EvalRun.id == str(eval_id))
    )
    eval_run = result.scalar_one_or_none()
    if not eval_run:
        raise HTTPException(status_code=404, detail="Eval run not found")
    return eval_run


@router.post("/evals/{eval_id}/run")
async def execute_eval(
    eval_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """触发评估执行（后台异步执行）."""
    result = await db.execute(
        select(EvalRun).where(EvalRun.id == str(eval_id))
    )
    eval_run = result.scalar_one_or_none()
    if not eval_run:
        raise HTTPException(status_code=404, detail="Eval run not found")

    if eval_run.status == "running":
        raise HTTPException(status_code=409, detail="Eval run already in progress")

    # 在后台执行评估
    async def _run_eval():
        runner = EvalRunner()
        agent_config = None
        if eval_run.dataset and len(eval_run.dataset) > 0:
            # 简化：不传入 agent_config，使用 dataset 中的 actual 字段
            pass
        await runner.run(eval_run, agent_config=agent_config)
        # 保存结果
        async with get_db() as session:
            session.add(eval_run)
            await session.commit()

    background_tasks.add_task(_run_eval)
    return {"id": eval_id, "status": "started"}


@router.delete("/evals/{eval_id}")
async def delete_eval_run(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """删除评估运行."""
    result = await db.execute(
        select(EvalRun).where(EvalRun.id == str(eval_id))
    )
    eval_run = result.scalar_one_or_none()
    if not eval_run:
        raise HTTPException(status_code=404, detail="Eval run not found")

    await db.delete(eval_run)

    return {"id": eval_id, "deleted": True}

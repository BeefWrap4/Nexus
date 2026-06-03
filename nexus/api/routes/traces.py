"""LLM Trace 查询 API.

Phase 6.1: Trace Viewer 后端接口。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import get_db
from nexus.models.llm_trace import LLMCallTrace
from nexus.security.auth import get_current_user

router = APIRouter()


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------

class LLMTraceOut(BaseModel):
    id: UUID
    tenant_id: UUID
    run_id: UUID | None = None
    node_id: str | None = None
    agent_id: str | None = None
    experiment_id: UUID | None = None
    model: str
    provider: str | None = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    retry_count: int
    fallback_model: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class LLMTraceDetail(LLMTraceOut):
    system_prompt: str | None = None
    user_prompt: str | None = None
    response_content: str | None = None
    response_reasoning: str | None = None
    tool_calls: list[dict] | None = None
    raw_response: dict[str, Any] | None = None


class TraceSummary(BaseModel):
    model: str
    total_calls: int
    avg_latency_ms: float
    avg_prompt_tokens: float
    avg_completion_tokens: float
    total_tokens: int


class TraceListResponse(BaseModel):
    total: int
    items: list[LLMTraceOut]


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@router.get("/traces", response_model=TraceListResponse)
async def list_traces(
    run_id: UUID | None = None,
    agent_id: str | None = None,
    model: str | None = None,
    experiment_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """列出 LLM 调用追踪记录."""
    stmt = select(LLMCallTrace).order_by(desc(LLMCallTrace.created_at))

    # 按 tenant_id 过滤（多租户安全）
    tenant_id = getattr(current_user, "tenant_id", None)
    if tenant_id:
        stmt = stmt.where(LLMCallTrace.tenant_id == str(tenant_id))

    if run_id:
        stmt = stmt.where(LLMCallTrace.run_id == str(run_id))
    if agent_id:
        stmt = stmt.where(LLMCallTrace.agent_id == agent_id)
    if model:
        stmt = stmt.where(LLMCallTrace.model == model)
    if experiment_id:
        stmt = stmt.where(LLMCallTrace.experiment_id == str(experiment_id))

    # 计数
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # 分页
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    items = result.scalars().all()

    return TraceListResponse(total=total, items=items)


@router.get("/traces/{trace_id}", response_model=LLMTraceDetail)
async def get_trace(
    trace_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """获取单个 Trace 详情（含完整 prompt/response）."""
    result = await db.execute(
        select(LLMCallTrace).where(LLMCallTrace.id == str(trace_id))
    )
    trace = result.scalar_one_or_none()
    if not trace:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@router.get("/traces/stats/summary")
async def get_trace_summary(
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """按 model 聚合的统计：调用次数、平均耗时、平均 token."""
    from sqlalchemy import cast, Float

    stmt = (
        select(
            LLMCallTrace.model,
            func.count().label("total_calls"),
            func.avg(cast(LLMCallTrace.latency_ms, Float)).label("avg_latency_ms"),
            func.avg(cast(LLMCallTrace.prompt_tokens, Float)).label("avg_prompt_tokens"),
            func.avg(cast(LLMCallTrace.completion_tokens, Float)).label(
                "avg_completion_tokens"
            ),
            func.sum(LLMCallTrace.total_tokens).label("total_tokens"),
        )
        .group_by(LLMCallTrace.model)
        .order_by(desc("total_calls"))
    )

    tenant_id = getattr(current_user, "tenant_id", None)
    if tenant_id:
        stmt = stmt.where(LLMCallTrace.tenant_id == str(tenant_id))

    if start_date:
        stmt = stmt.where(LLMCallTrace.created_at >= start_date)
    if end_date:
        stmt = stmt.where(LLMCallTrace.created_at <= end_date)

    result = await db.execute(stmt)
    rows = result.all()

    return [
        TraceSummary(
            model=row.model,
            total_calls=row.total_calls,
            avg_latency_ms=round(row.avg_latency_ms or 0, 2),
            avg_prompt_tokens=round(row.avg_prompt_tokens or 0, 2),
            avg_completion_tokens=round(row.avg_completion_tokens or 0, 2),
            total_tokens=row.total_tokens or 0,
        )
        for row in rows
    ]

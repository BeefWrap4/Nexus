"""LLM Trace 查询 API.

Phase 6.1: Trace Viewer 后端接口。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import get_db
from nexus.security.auth import get_current_user
from nexus.services.trace import TraceService

router = APIRouter()

trace_service = TraceService()


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
    cache_hit: bool | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


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
    tenant_id = current_user.get("tenant_id", "default")
    items, total = await trace_service.list_traces(
        db,
        tenant_id=tenant_id,
        run_id=run_id,
        agent_id=agent_id,
        model=model,
        experiment_id=experiment_id,
        skip=offset,
        limit=limit,
    )
    return TraceListResponse(total=total, items=items)


@router.get("/traces/{trace_id}", response_model=LLMTraceDetail)
async def get_trace(
    trace_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """获取单个 Trace 详情（含完整 prompt/response）."""
    trace = await trace_service.get_trace(db, trace_id)
    if not trace:
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
    tenant_id = current_user.get("tenant_id", "default")
    rows = await trace_service.get_summary(
        db,
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
    )
    return [
        TraceSummary(
            model=row["model"],
            total_calls=row["total_calls"],
            avg_latency_ms=row["avg_latency_ms"],
            avg_prompt_tokens=row["avg_prompt_tokens"],
            avg_completion_tokens=row["avg_completion_tokens"],
            total_tokens=row["total_tokens"],
        )
        for row in rows
    ]

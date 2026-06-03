"""Code Review API routes.

Phase 8.1: Interactive review workbench — submit review + get results.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import get_db
from nexus.security.auth import get_current_user
from nexus.services.code_review import CodeReviewService

router = APIRouter()

code_review_service = CodeReviewService()


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------

class ReviewSubmitRequest(BaseModel):
    """Submit code review request."""

    diff_content: str = Field(..., description="Git diff or code content to review")
    language: str = Field(default="auto", description="Programming language (auto-detected if 'auto')")
    focus_areas: str = Field(
        default="security, performance, maintainability, correctness",
        description="Comma-separated focus areas",
    )
    strictness: str = Field(
        default="normal",
        description="Review strictness: strict, normal, relaxed",
    )
    template_id: UUID | None = None  # Optional prompt template ID


class ReviewResponse(BaseModel):
    """Review result response."""

    run_id: UUID
    status: str


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@router.post("/reviews", response_model=ReviewResponse)
async def submit_review(
    data: ReviewSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """Submit code review — create persistent run and enqueue for execution."""
    tenant_id = current_user.get("tenant_id")
    result = await code_review_service.submit_review(
        db,
        tenant_id=tenant_id,
        diff_content=data.diff_content,
        language=data.language,
        focus_areas=data.focus_areas,
        strictness=data.strictness,
        template_id=data.template_id,
    )
    return ReviewResponse(run_id=UUID(result["run_id"]), status=result["status"])


@router.get("/reviews/{run_id}")
async def get_review_result(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """Get review result by querying run status via CodeReviewService."""
    tenant_id = current_user.get("tenant_id")
    result = await code_review_service.get_review_result(db, run_id, tenant_id)
    if not result:
        raise HTTPException(status_code=404, detail="Review run not found")
    return result

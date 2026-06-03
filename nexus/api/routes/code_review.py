"""Code Review API routes.

Phase 8.1: Interactive review workbench — submit review + stream results.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import get_db
from nexus.engine.checkpoint import CheckpointManager
from nexus.engine.enums import NodeType
from nexus.engine.event_bus import EventBus
from nexus.engine.node_executors import (
    AgentNodeExecutor,
    EndNodeExecutor,
    StartNodeExecutor,
    ToolNodeExecutor,
)
from nexus.engine.router_engine import RouterEngine
from nexus.engine.state_manager import StateManager
from nexus.engine.variable_pool import VariablePool
from nexus.engine.workflow_engine import Edge, Node, WorkflowDefinition, WorkflowEngine
from nexus.security.auth import get_current_user
from nexus.services.run import RunService
from nexus.tools.registry import get_tool_registry

router = APIRouter()


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


@router.post("/reviews", response_model=ReviewResponse)
async def submit_review(
    data: ReviewSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """Submit code review — trigger workflow execution."""
    tenant_id = current_user.get("tenant_id")
    run_id = uuid4()

    # Build review workflow
    registry = get_tool_registry()
    event_bus = EventBus()

    wf = WorkflowDefinition(
        nodes=[
            Node(id="start", type=NodeType.START),
            Node(
                id="review",
                type=NodeType.AGENT,
                config={
                    "agent_name": "code-reviewer",
                    "agent_role": "senior software engineer performing code review",
                    "agent_goal": "Thoroughly review code and produce a structured review report",
                    "task_description": data.diff_content,
                    "system_prompt_template_id": str(data.template_id) if data.template_id else None,
                    "template_variables": {
                        "role": "senior software engineer",
                        "language": data.language,
                        "focus_areas": data.focus_areas,
                        "strictness": data.strictness,
                        "diff_content": data.diff_content,
                    },
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                },
            ),
            Node(id="end", type=NodeType.END),
        ],
        edges=[
            Edge(source="start", target="review"),
            Edge(source="review", target="end"),
        ],
    )

    engine = WorkflowEngine(
        state_manager=StateManager(),
        event_bus=event_bus,
        checkpoint_mgr=CheckpointManager(),
        variable_pool=VariablePool(),
        router_engine=RouterEngine(),
    )

    engine.register_executor(NodeType.START, StartNodeExecutor())
    engine.register_executor(NodeType.END, EndNodeExecutor())
    engine.register_executor(NodeType.AGENT, AgentNodeExecutor(tool_registry=registry))
    engine.register_executor(
        NodeType.TOOL, ToolNodeExecutor(tool_registry=registry, event_bus=event_bus)
    )

    # Execute in background (progress streamed via EventBus → WebSocket)
    async def _run():
        return await engine.execute(
            workflow_def=wf,
            trigger_payload={"diff_content": data.diff_content},
            run_id=str(run_id),
        )

    asyncio.create_task(_run())

    return ReviewResponse(run_id=run_id, status="started")


@router.get("/reviews/{run_id}")
async def get_review_result(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """Get review result by querying run status via RunService."""
    run_service = RunService()
    tenant_id = UUID(current_user.get("tenant_id"))
    run = await run_service.get(db, run_id, tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="Review run not found")
    return {"run_id": run_id, "status": run.status, "result": run.result}

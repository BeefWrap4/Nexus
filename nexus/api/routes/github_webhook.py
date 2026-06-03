"""GitHub Webhook route — Phase 8.2 PR review bot.

Receives GitHub pull_request webhooks, triggers code review workflow,
and posts review comments back to GitHub.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request
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
from nexus.tools.registry import get_tool_registry

router = APIRouter()

_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")


class PRReviewConfig(BaseModel):
    """Configuration for PR auto-review."""

    language: str = Field(default="auto", description="Programming language")
    focus_areas: str = Field(
        default="security, performance, maintainability, correctness",
    )
    strictness: str = Field(default="normal")
    auto_review: bool = Field(default=True, description="Auto-review on PR open/update")


@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
    x_github_event: str | None = Header(None, alias="X-GitHub-Event"),
):
    """Receive GitHub webhook and trigger code review."""
    body = await request.body()

    # Verify signature
    if _WEBHOOK_SECRET:
        if not x_hub_signature_256:
            raise HTTPException(status_code=401, detail="Missing signature")
        expected = "sha256=" + hmac.new(
            _WEBHOOK_SECRET.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(body)

    # Only handle pull_request events
    if x_github_event != "pull_request":
        return {"status": "ignored", "event": x_github_event}

    action = payload.get("action", "")
    if action not in ("opened", "synchronize", "reopened"):
        return {"status": "ignored", "action": action}

    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {})

    owner = repo.get("owner", {}).get("login", "")
    repo_name = repo.get("name", "")
    pull_number = pr.get("number", 0)
    diff_url = pr.get("diff_url", "")

    if not owner or not repo_name or not pull_number:
        raise HTTPException(status_code=400, detail="Invalid PR payload")

    # Trigger review workflow
    run_id = uuid4()
    registry = get_tool_registry()
    event_bus = EventBus()

    wf = WorkflowDefinition(
        nodes=[
            Node(id="start", type=NodeType.START),
            Node(
                id="fetch_diff",
                type=NodeType.TOOL,
                config={
                    "tool_name": "github_get_pr_diff",
                    "tool_params": {
                        "owner": owner,
                        "repo": repo_name,
                        "pull_number": pull_number,
                    },
                },
            ),
            Node(
                id="review",
                type=NodeType.AGENT,
                config={
                    "agent_name": "pr-code-reviewer",
                    "agent_role": "senior software engineer performing PR code review",
                    "agent_goal": "Review PR diff and produce a structured review report",
                    "task_description": (
                        "Review the PR diff. First call parse_diff to structure it, "
                        "then detect_language, security_check, perf_check, and style_check "
                        "to find deterministic issues. Finally use your expertise for logic/design review.\n"
                        "Output a concise review report with findings and suggestions."
                    ),
                    "template_variables": {
                        "role": "senior software engineer",
                        "language": "auto",
                        "focus_areas": "security, performance, maintainability, correctness",
                        "strictness": "normal",
                        "diff_content": "{{#fetch_diff.output.diff#}}",
                    },
                    "provider": "deepseek",
                    "model": "deepseek-v4-pro",
                    "temperature": 0.3,
                    "max_iterations": 15,
                },
            ),
            Node(
                id="post_review",
                type=NodeType.TOOL,
                config={
                    "tool_name": "github_post_review_comment",
                    "tool_params": {
                        "owner": owner,
                        "repo": repo_name,
                        "pull_number": pull_number,
                        "body": "{{#review.output#}}",
                    },
                },
            ),
            Node(id="end", type=NodeType.END),
        ],
        edges=[
            Edge(source="start", target="fetch_diff"),
            Edge(source="fetch_diff", target="review"),
            Edge(source="review", target="post_review"),
            Edge(source="post_review", target="end"),
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

    async def _run():
        return await engine.execute(
            workflow_def=wf,
            trigger_payload={"pr": pr},
            run_id=str(run_id),
        )

    asyncio.create_task(_run())

    return {
        "status": "review_started",
        "run_id": str(run_id),
        "owner": owner,
        "repo": repo_name,
        "pull_number": pull_number,
    }


@router.get("/webhooks/github/config")
async def get_github_config():
    """Get current GitHub webhook configuration status."""
    return {
        "webhook_secret_configured": bool(_WEBHOOK_SECRET),
        "github_token_configured": bool(os.environ.get("GITHUB_TOKEN")),
    }

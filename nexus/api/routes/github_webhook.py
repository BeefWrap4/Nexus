"""GitHub Webhook route — Phase 8.2 PR review bot.

Receives GitHub pull_request webhooks, triggers code review workflow,
and posts review comments back to GitHub.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request

from nexus.db.database import get_db_session
from nexus.services.code_review import CodeReviewService

router = APIRouter()

_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
code_review_service = CodeReviewService()


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
    else:
        # 生产环境必须配置 GITHUB_WEBHOOK_SECRET
        raise HTTPException(
            status_code=401,
            detail="GITHUB_WEBHOOK_SECRET not configured",
        )

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

    if not owner or not repo_name or not pull_number:
        raise HTTPException(status_code=400, detail="Invalid PR payload")

    # Trigger review via CodeReviewService (persistent run + ARQ enqueue)
    # Note: Webhook has no authenticated user, use a default tenant
    async with get_db_session() as db:
        result = await code_review_service.submit_pr_review(
            db,
            tenant_id=UUID("00000000-0000-0000-0000-000000000000"),
            owner=owner,
            repo=repo_name,
            pull_number=pull_number,
            pr_data=pr,
        )

    return {
        "status": "review_started",
        "run_id": result["run_id"],
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

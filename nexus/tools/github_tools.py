"""GitHub Tools — Phase 8.2 PR review bot.

Provides deterministic GitHub API interactions as NEXUS Tools.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

from nexus.tools.registry import Tool, ToolResult, ToolType

logger = structlog.get_logger()

_GITHUB_API_BASE = "https://api.github.com"


def build_github_tools() -> list[Tool]:
    """Build GitHub tool definitions."""
    return [
        Tool(
            name="github_get_pr_diff",
            description="Fetch a pull request diff from GitHub",
            type=ToolType.PYTHON,
            config={},
            handler=_handle_get_pr_diff,
            schema={
                "type": "object",
                "required": ["owner", "repo", "pull_number"],
                "properties": {
                    "owner": {"type": "string", "description": "Repository owner"},
                    "repo": {"type": "string", "description": "Repository name"},
                    "pull_number": {"type": "integer", "description": "PR number"},
                },
            },
        ),
        Tool(
            name="github_post_review_comment",
            description="Post a review comment on a GitHub PR",
            type=ToolType.PYTHON,
            config={},
            handler=_handle_post_review_comment,
            schema={
                "type": "object",
                "required": ["owner", "repo", "pull_number", "body"],
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "pull_number": {"type": "integer"},
                    "body": {"type": "string", "description": "Review comment body"},
                    "commit_id": {"type": "string", "description": "Commit SHA to attach comment to"},
                    "path": {"type": "string", "description": "File path for line comment"},
                    "line": {"type": "integer", "description": "Line number for comment"},
                },
            },
        ),
        Tool(
            name="github_list_pr_files",
            description="List files changed in a PR",
            type=ToolType.PYTHON,
            config={},
            handler=_handle_list_pr_files,
            schema={
                "type": "object",
                "required": ["owner", "repo", "pull_number"],
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "pull_number": {"type": "integer"},
                },
            },
        ),
    ]


def register_github_tools(registry) -> None:
    """Register GitHub tools into ToolRegistry."""
    tools = build_github_tools()
    for tool in tools:
        registry.register(tool)
    logger.info("github_tools_registered", count=len(tools))


# --- Handler Implementations ---

async def _handle_get_pr_diff(
    params: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> ToolResult:
    """Fetch PR diff from GitHub."""
    owner = params.get("owner", "")
    repo = params.get("repo", "")
    pull_number = params.get("pull_number", 0)
    token = _get_github_token()

    if not token:
        return ToolResult(success=False, error="GitHub token not configured (GITHUB_TOKEN env var)")

    url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pull_number}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3.diff",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return ToolResult(
                success=True,
                data={
                    "diff": response.text,
                    "owner": owner,
                    "repo": repo,
                    "pull_number": pull_number,
                },
            )
    except httpx.HTTPStatusError as e:
        return ToolResult(
            success=False,
            error=f"GitHub API error {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to fetch PR diff: {str(e)}")


async def _handle_post_review_comment(
    params: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> ToolResult:
    """Post a review comment on a PR."""
    owner = params.get("owner", "")
    repo = params.get("repo", "")
    pull_number = params.get("pull_number", 0)
    body = params.get("body", "")
    token = _get_github_token()

    if not token:
        return ToolResult(success=False, error="GitHub token not configured")

    url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pull_number}/reviews"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    payload: dict[str, Any] = {"body": body, "event": "COMMENT"}

    # Optional line-level comment
    commit_id = params.get("commit_id")
    path = params.get("path")
    line = params.get("line")
    if path and line is not None:
        payload["comments"] = [
            {
                "path": path,
                "line": line,
                "body": body,
                **({"commit_id": commit_id} if commit_id else {}),
            }
        ]

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return ToolResult(
                success=True,
                data={"review_id": data.get("id"), "html_url": data.get("html_url")},
            )
    except httpx.HTTPStatusError as e:
        return ToolResult(
            success=False,
            error=f"GitHub API error {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to post comment: {str(e)}")


async def _handle_list_pr_files(
    params: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> ToolResult:
    """List files changed in a PR."""
    owner = params.get("owner", "")
    repo = params.get("repo", "")
    pull_number = params.get("pull_number", 0)
    token = _get_github_token()

    if not token:
        return ToolResult(success=False, error="GitHub token not configured")

    url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pull_number}/files"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            files = response.json()
            return ToolResult(
                success=True,
                data={
                    "files": [
                        {
                            "filename": f.get("filename"),
                            "status": f.get("status"),
                            "additions": f.get("additions"),
                            "deletions": f.get("deletions"),
                            "patch": f.get("patch"),
                        }
                        for f in files
                    ],
                    "total": len(files),
                },
            )
    except httpx.HTTPStatusError as e:
        return ToolResult(
            success=False,
            error=f"GitHub API error {e.response.status_code}: {e.response.text}",
        )
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to list PR files: {str(e)}")


def _get_github_token() -> str:
    """Get GitHub token from environment."""
    return os.environ.get("GITHUB_TOKEN", "")

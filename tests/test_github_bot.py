"""GitHub PR Bot tests — Phase 8.2.

Covers:
- github_get_pr_diff: success, 404, no token
- github_post_review_comment: success, line-level comment, no token
- github_list_pr_files: success, pagination
- Webhook handler: signature verification, PR events, ignored events
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from nexus.api.main import app
from nexus.tools.github_tools import (
    _get_github_token,
    _handle_get_pr_diff,
    _handle_list_pr_files,
    _handle_post_review_comment,
    build_github_tools,
    register_github_tools,
)
from nexus.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# GitHub Token Helper
# ---------------------------------------------------------------------------

class TestGetGitHubToken:
    def test_token_from_env(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_123")
        assert _get_github_token() == "ghp_test_123"

    def test_token_missing(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert _get_github_token() == ""


# ---------------------------------------------------------------------------
# github_get_pr_diff
# ---------------------------------------------------------------------------

class TestGetPRDiff:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "diff --git a/main.py b/main.py\n+hello"
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _handle_get_pr_diff(
                {"owner": "test-org", "repo": "test-repo", "pull_number": 42}
            )

        assert result.success is True
        assert result.data["diff"] == "diff --git a/main.py b/main.py\n+hello"
        assert result.data["owner"] == "test-org"
        assert result.data["repo"] == "test-repo"
        assert result.data["pull_number"] == 42

        # Verify correct URL and headers were used
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert "repos/test-org/test-repo/pulls/42" in call_args[0][0]
        headers = call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer ghp_test_123"
        assert headers["Accept"] == "application/vnd.github.v3.diff"

    @pytest.mark.asyncio
    async def test_no_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        result = await _handle_get_pr_diff(
            {"owner": "test-org", "repo": "test-repo", "pull_number": 42}
        )
        assert result.success is False
        assert "token not configured" in result.error.lower()

    @pytest.mark.asyncio
    async def test_404_not_found(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_123")

        from httpx import HTTPStatusError

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = '{"message": "Not Found"}'

        err = HTTPStatusError(
            "Not Found",
            request=MagicMock(),
            response=mock_response,
        )
        mock_response.raise_for_status = MagicMock(side_effect=err)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _handle_get_pr_diff(
                {"owner": "test-org", "repo": "test-repo", "pull_number": 999}
            )

        assert result.success is False
        assert "404" in result.error


# ---------------------------------------------------------------------------
# github_post_review_comment
# ---------------------------------------------------------------------------

class TestPostReviewComment:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 12345, "html_url": "https://github.com/test-org/test-repo/pull/42#discussion_r12345"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _handle_post_review_comment(
                {
                    "owner": "test-org",
                    "repo": "test-repo",
                    "pull_number": 42,
                    "body": "LGTM! Great work.",
                }
            )

        assert result.success is True
        assert result.data["review_id"] == 12345
        assert "html_url" in result.data

        # Verify payload
        call_args = mock_client.post.call_args
        payload = call_args[1]["json"]
        assert payload["body"] == "LGTM! Great work."
        assert payload["event"] == "COMMENT"
        assert "comments" not in payload  # No line-level comment

    @pytest.mark.asyncio
    async def test_line_level_comment(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 12346}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _handle_post_review_comment(
                {
                    "owner": "test-org",
                    "repo": "test-repo",
                    "pull_number": 42,
                    "body": "Consider using a constant here.",
                    "path": "src/main.py",
                    "line": 15,
                    "commit_id": "abc123",
                }
            )

        assert result.success is True
        call_args = mock_client.post.call_args
        payload = call_args[1]["json"]
        assert "comments" in payload
        assert payload["comments"][0]["path"] == "src/main.py"
        assert payload["comments"][0]["line"] == 15
        assert payload["comments"][0]["commit_id"] == "abc123"

    @pytest.mark.asyncio
    async def test_no_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        result = await _handle_post_review_comment(
            {"owner": "test-org", "repo": "test-repo", "pull_number": 42, "body": "test"}
        )
        assert result.success is False
        assert "token not configured" in result.error.lower()


# ---------------------------------------------------------------------------
# github_list_pr_files
# ---------------------------------------------------------------------------

class TestListPRFiles:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "filename": "src/main.py",
                "status": "modified",
                "additions": 10,
                "deletions": 2,
                "patch": "@@ -1,5 +1,10 @@",
            },
            {
                "filename": "tests/test_main.py",
                "status": "added",
                "additions": 50,
                "deletions": 0,
                "patch": None,
            },
        ]
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _handle_list_pr_files(
                {"owner": "test-org", "repo": "test-repo", "pull_number": 42}
            )

        assert result.success is True
        assert result.data["total"] == 2
        assert len(result.data["files"]) == 2
        assert result.data["files"][0]["filename"] == "src/main.py"
        assert result.data["files"][0]["status"] == "modified"
        assert result.data["files"][1]["status"] == "added"

    @pytest.mark.asyncio
    async def test_no_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        result = await _handle_list_pr_files(
            {"owner": "test-org", "repo": "test-repo", "pull_number": 42}
        )
        assert result.success is False
        assert "token not configured" in result.error.lower()


# ---------------------------------------------------------------------------
# Tool Registry Registration
# ---------------------------------------------------------------------------

class TestRegisterGitHubTools:
    def test_registration(self):
        registry = ToolRegistry()
        register_github_tools(registry)

        tools = registry.list_tools()
        tool_names = {t.name for t in tools}
        assert "github_get_pr_diff" in tool_names
        assert "github_post_review_comment" in tool_names
        assert "github_list_pr_files" in tool_names

    def test_build_github_tools(self):
        tools = build_github_tools()
        assert len(tools) == 3
        for tool in tools:
            assert tool.type.value == "python"
            assert tool.handler is not None


# ---------------------------------------------------------------------------
# Webhook Handler
# ---------------------------------------------------------------------------

class TestGitHubWebhook:
    def _make_signature(self, body_bytes: bytes, secret: str) -> str:
        sig = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
        return f"sha256={sig}"

    @pytest.mark.asyncio
    async def test_missing_signature_with_secret(self, monkeypatch, async_client: AsyncClient):
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "mysecret")
        # Patch the module-level variable that was already read at import time
        with patch("nexus.api.routes.github_webhook._WEBHOOK_SECRET", "mysecret"):
            response = await async_client.post(
                "/api/v1/webhooks/github",
                json={"action": "opened", "pull_request": {"number": 1}},
            )
        assert response.status_code == 401
        assert "Missing signature" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_invalid_signature(self, monkeypatch, async_client: AsyncClient):
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "mysecret")
        with patch("nexus.api.routes.github_webhook._WEBHOOK_SECRET", "mysecret"):
            response = await async_client.post(
                "/api/v1/webhooks/github",
                json={"action": "opened", "pull_request": {"number": 1}},
                headers={"X-Hub-Signature-256": "sha256=invalid"},
            )
        assert response.status_code == 401
        assert "Invalid signature" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_valid_signature_pr_opened(self, monkeypatch, async_client: AsyncClient):
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "mysecret")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")

        payload = {
            "action": "opened",
            "pull_request": {
                "number": 42,
                "diff_url": "https://github.com/test-org/test-repo/pull/42.diff",
            },
            "repository": {
                "name": "test-repo",
                "owner": {"login": "test-org"},
            },
        }
        # Compute signature from the exact bytes httpx will send
        body_bytes = json.dumps(payload).encode()
        sig = self._make_signature(body_bytes, "mysecret")

        # Patch the module-level secret and mock the workflow execution
        with patch("nexus.api.routes.github_webhook._WEBHOOK_SECRET", "mysecret"):
            with patch("nexus.api.routes.github_webhook.WorkflowEngine") as mock_engine_cls:
                mock_engine = AsyncMock()
                mock_engine.execute = AsyncMock(return_value={"status": "completed"})
                mock_engine_cls.return_value = mock_engine

                response = await async_client.post(
                    "/api/v1/webhooks/github",
                    content=body_bytes,
                    headers={
                        "X-Hub-Signature-256": sig,
                        "X-GitHub-Event": "pull_request",
                        "Content-Type": "application/json",
                    },
                )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "review_started"
        assert data["owner"] == "test-org"
        assert data["repo"] == "test-repo"
        assert data["pull_number"] == 42
        assert "run_id" in data

    @pytest.mark.asyncio
    async def test_ignored_event_type(self, monkeypatch, async_client: AsyncClient):
        with patch("nexus.api.routes.github_webhook._WEBHOOK_SECRET", ""):
            response = await async_client.post(
                "/api/v1/webhooks/github",
                json={"action": "labeled"},
                headers={"X-GitHub-Event": "pull_request"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    @pytest.mark.asyncio
    async def test_non_pr_event(self, monkeypatch, async_client: AsyncClient):
        with patch("nexus.api.routes.github_webhook._WEBHOOK_SECRET", ""):
            response = await async_client.post(
                "/api/v1/webhooks/github",
                json={"ref": "refs/heads/main"},
                headers={"X-GitHub-Event": "push"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
        assert response.json()["event"] == "push"

    @pytest.mark.asyncio
    async def test_invalid_payload_missing_pr(self, monkeypatch, async_client: AsyncClient):
        with patch("nexus.api.routes.github_webhook._WEBHOOK_SECRET", ""):
            response = await async_client.post(
                "/api/v1/webhooks/github",
                json={
                    "action": "opened",
                    "pull_request": {},
                    "repository": {"name": "test-repo", "owner": {"login": ""}},
                },
                headers={"X-GitHub-Event": "pull_request"},
            )
        assert response.status_code == 400
        assert "Invalid PR payload" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Webhook Config Endpoint
# ---------------------------------------------------------------------------

class TestGitHubConfig:
    @pytest.mark.asyncio
    async def test_config_status(self, monkeypatch, async_client: AsyncClient):
        with patch("nexus.api.routes.github_webhook._WEBHOOK_SECRET", "configured"):
            with patch("nexus.api.routes.github_webhook.os.environ.get", side_effect=lambda key, default="": {
                "GITHUB_TOKEN": "ghp_token",
            }.get(key, default)):
                response = await async_client.get("/api/v1/webhooks/github/config")
        assert response.status_code == 200
        data = response.json()
        assert data["webhook_secret_configured"] is True
        assert data["github_token_configured"] is True

    @pytest.mark.asyncio
    async def test_config_status_unconfigured(self, monkeypatch, async_client: AsyncClient):
        with patch("nexus.api.routes.github_webhook._WEBHOOK_SECRET", ""):
            with patch("nexus.api.routes.github_webhook.os.environ.get", return_value=""):
                response = await async_client.get("/api/v1/webhooks/github/config")
        assert response.status_code == 200
        data = response.json()
        assert data["webhook_secret_configured"] is False
        assert data["github_token_configured"] is False

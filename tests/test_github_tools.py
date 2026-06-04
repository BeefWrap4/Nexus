"""GitHub Tools 测试 — 覆盖 github_tools 模块.

覆盖:
- build_github_tools 工具定义
- register_github_tools 注册
- _get_github_token 令牌获取
- _handle_get_pr_diff / _handle_post_review_comment / _handle_list_pr_files
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from nexus.tools.github_tools import (
    build_github_tools,
    register_github_tools,
    _get_github_token,
    _handle_get_pr_diff,
    _handle_post_review_comment,
    _handle_list_pr_files,
)
from nexus.tools.registry import Tool, ToolRegistry, ToolType, ToolResult


class TestBuildGitHubTools:
    """测试 build_github_tools 工具定义."""

    def test_build_returns_three_tools(self):
        """应返回 3 个 GitHub Tools."""
        tools = build_github_tools()
        assert len(tools) == 3

    def test_tool_names(self):
        """工具名称正确."""
        tools = build_github_tools()
        names = {t.name for t in tools}
        assert names == {
            "github_get_pr_diff",
            "github_post_review_comment",
            "github_list_pr_files",
        }

    def test_all_python_type(self):
        """所有工具均为 PYTHON 类型."""
        tools = build_github_tools()
        for tool in tools:
            assert tool.type == ToolType.PYTHON

    def test_tools_have_handlers(self):
        """每个工具都有 handler."""
        tools = build_github_tools()
        for tool in tools:
            assert tool.handler is not None

    def test_get_pr_diff_schema(self):
        """github_get_pr_diff 的 schema 包含 owner, repo, pull_number."""
        tools = {t.name: t for t in build_github_tools()}
        diff_tool = tools["github_get_pr_diff"]
        assert diff_tool.schema["required"] == ["owner", "repo", "pull_number"]
        assert "owner" in diff_tool.schema["properties"]
        assert "repo" in diff_tool.schema["properties"]
        assert "pull_number" in diff_tool.schema["properties"]


class TestRegisterGitHubTools:
    """测试 register_github_tools 注册."""

    def test_register_adds_tools_to_registry(self):
        """注册后 registry 应包含 GitHub Tools."""
        registry = ToolRegistry()
        register_github_tools(registry)

        tools = registry.list_tools()
        names = {t.name for t in tools}
        assert "github_get_pr_diff" in names
        assert "github_post_review_comment" in names
        assert "github_list_pr_files" in names


class TestGetGitHubToken:
    """测试 _get_github_token."""

    def test_returns_token_when_set(self, monkeypatch):
        """环境变量设置时返回 token."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        assert _get_github_token() == "ghp_test123"

    def test_returns_empty_when_not_set(self, monkeypatch):
        """环境变量未设置时返回空字符串."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert _get_github_token() == ""


class TestHandleGetPRDiff:
    """测试 _handle_get_pr_diff handler."""

    @pytest.mark.asyncio
    async def test_missing_token_returns_error(self, monkeypatch):
        """缺少 token 时返回失败结果."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        result = await _handle_get_pr_diff({
            "owner": "test", "repo": "test", "pull_number": 1
        })
        assert result.success is False
        assert "token" in result.error.lower()

    @respx.mock
    @pytest.mark.asyncio
    async def test_successful_diff_fetch(self, monkeypatch):
        """成功获取 PR diff."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
        route = respx.get(
            "https://api.github.com/repos/owner/repo/pulls/42"
        ).mock(return_value=httpx.Response(200, text="diff --git a/file.py"))

        result = await _handle_get_pr_diff({
            "owner": "owner", "repo": "repo", "pull_number": 42
        })

        assert result.success is True
        assert result.data["diff"] == "diff --git a/file.py"
        assert result.data["owner"] == "owner"
        assert result.data["pull_number"] == 42
        assert route.called
        # verify accept header for diff
        req = route.calls.last.request
        assert req.headers["Accept"] == "application/vnd.github.v3.diff"

    @respx.mock
    @pytest.mark.asyncio
    async def test_http_error_returns_failure(self, monkeypatch):
        """HTTP 错误返回失败结果."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
        respx.get(
            "https://api.github.com/repos/o/r/pulls/1"
        ).mock(return_value=httpx.Response(404, text="Not Found"))

        result = await _handle_get_pr_diff({
            "owner": "o", "repo": "r", "pull_number": 1
        })

        assert result.success is False
        assert "404" in result.error

    @respx.mock
    @pytest.mark.asyncio
    async def test_generic_exception_returns_failure(self, monkeypatch):
        """网络异常返回失败结果."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
        respx.get(
            "https://api.github.com/repos/o/r/pulls/1"
        ).mock(side_effect=Exception("Network error"))

        result = await _handle_get_pr_diff({
            "owner": "o", "repo": "r", "pull_number": 1
        })

        assert result.success is False
        assert "Network error" in result.error


class TestHandlePostReviewComment:
    """测试 _handle_post_review_comment handler."""

    @pytest.mark.asyncio
    async def test_missing_token_returns_error(self, monkeypatch):
        """缺少 token 时返回失败结果."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        result = await _handle_post_review_comment({
            "owner": "o", "repo": "r", "pull_number": 1, "body": "LGTM"
        })
        assert result.success is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_successful_comment_post(self, monkeypatch):
        """成功发布 review comment."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
        route = respx.post(
            "https://api.github.com/repos/o/r/pulls/1/reviews"
        ).mock(return_value=httpx.Response(
            200, json={"id": 123, "html_url": "https://github.com/o/r/pull/1#review-123"}
        ))

        result = await _handle_post_review_comment({
            "owner": "o", "repo": "r", "pull_number": 1, "body": "Nice work!"
        })

        assert result.success is True
        assert result.data["review_id"] == 123
        assert "html_url" in result.data
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_review_with_line_comment(self, monkeypatch):
        """带行号的 review comment."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
        route = respx.post(
            "https://api.github.com/repos/o/r/pulls/1/reviews"
        ).mock(return_value=httpx.Response(200, json={"id": 456}))

        result = await _handle_post_review_comment({
            "owner": "o",
            "repo": "r",
            "pull_number": 1,
            "body": "Fix this line",
            "commit_id": "abc123",
            "path": "src/main.py",
            "line": 42,
        })

        assert result.success is True
        # 验证 body 中包含 line comment
        import json
        req = route.calls.last.request
        body = json.loads(req.content)
        assert "comments" in body
        assert body["comments"][0]["path"] == "src/main.py"
        assert body["comments"][0]["line"] == 42
        assert body["comments"][0]["commit_id"] == "abc123"

    @respx.mock
    @pytest.mark.asyncio
    async def test_line_comment_without_commit_id(self, monkeypatch):
        """行注释不传 commit_id 时也不应失败."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
        route = respx.post(
            "https://api.github.com/repos/o/r/pulls/1/reviews"
        ).mock(return_value=httpx.Response(200, json={"id": 789}))

        result = await _handle_post_review_comment({
            "owner": "o",
            "repo": "r",
            "pull_number": 1,
            "body": "Nice",
            "path": "src/main.py",
            "line": 10,
        })

        assert result.success is True


class TestHandleListPRFiles:
    """测试 _handle_list_pr_files handler."""

    @pytest.mark.asyncio
    async def test_missing_token_returns_error(self, monkeypatch):
        """缺少 token 时返回失败结果."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        result = await _handle_list_pr_files({
            "owner": "o", "repo": "r", "pull_number": 1
        })
        assert result.success is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_successful_list_files(self, monkeypatch):
        """成功列出 PR 文件."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
        route = respx.get(
            "https://api.github.com/repos/o/r/pulls/1/files"
        ).mock(return_value=httpx.Response(200, json=[
            {"filename": "a.py", "status": "modified", "additions": 5, "deletions": 2, "patch": "@@ -1,3 +1,6 @@"},
            {"filename": "b.py", "status": "added", "additions": 10, "deletions": 0, "patch": None},
        ]))

        result = await _handle_list_pr_files({
            "owner": "o", "repo": "r", "pull_number": 1
        })

        assert result.success is True
        assert result.data["total"] == 2
        files = result.data["files"]
        assert files[0]["filename"] == "a.py"
        assert files[0]["status"] == "modified"
        assert files[0]["patch"] == "@@ -1,3 +1,6 @@"
        assert files[1]["filename"] == "b.py"
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_http_error_list_files(self, monkeypatch):
        """HTTP 错误时返回失败结果."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
        respx.get(
            "https://api.github.com/repos/o/r/pulls/1/files"
        ).mock(return_value=httpx.Response(404, text="Not Found"))

        result = await _handle_list_pr_files({
            "owner": "o", "repo": "r", "pull_number": 1
        })

        assert result.success is False
        assert "404" in result.error

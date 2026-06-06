import pytest
from nexus.tools.registry import ToolRegistry, ToolResult

ADMIN_CTX = {"user_role": "admin"}


class TestHttpTool:
    def test_register(self):
        from nexus.tools.connectors.http_tool import create_http_tools
        registry = ToolRegistry()
        create_http_tools(registry)
        assert "http_request" in registry._tools


class TestEmailTool:
    def test_register(self):
        from nexus.tools.connectors.email_tool import create_email_tool
        registry = ToolRegistry()
        create_email_tool(registry)
        assert "send_email" in registry._tools

    @pytest.mark.asyncio
    async def test_send_email_returns_success(self):
        registry = ToolRegistry()
        from nexus.tools.connectors.email_tool import create_email_tool
        create_email_tool(registry)
        result = await registry.execute(
            "send_email",
            {"to": "test@example.com", "subject": "Test", "body": "Hello"},
            context=ADMIN_CTX,
        )
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.data["sent"] is True


class TestWebhookTool:
    def test_register(self):
        from nexus.tools.connectors.webhook_tool import create_webhook_tool
        registry = ToolRegistry()
        create_webhook_tool(registry)
        assert "call_webhook" in registry._tools


class TestFileTools:
    def test_register(self):
        from nexus.tools.connectors.file_tool import create_file_tools
        registry = ToolRegistry()
        create_file_tools(registry)
        assert "read_file" in registry._tools
        assert "write_file" in registry._tools

    @pytest.mark.asyncio
    async def test_write_and_read_file(self, tmp_path, monkeypatch):
        from nexus.tools.connectors import file_tool
        from nexus.tools.connectors.file_tool import create_file_tools
        # 修复 (P1 测试): S4-2 加了 chroot, _WORKSPACE_ROOT 在 import 时
        # 锁定, 改 env 不够 — 直接 monkeypatch 模块级常量
        monkeypatch.setattr(file_tool, "_WORKSPACE_ROOT", str(tmp_path))
        registry = ToolRegistry()
        create_file_tools(registry)
        test_file = str(tmp_path / "test.txt")
        # Write
        write_result = await registry.execute(
            "write_file",
            {"path": test_file, "content": "Hello NEXUS"},
            context=ADMIN_CTX,
        )
        assert isinstance(write_result, ToolResult)
        assert write_result.success is True
        assert write_result.data["written"] is True
        # Read
        read_result = await registry.execute(
            "read_file",
            {"path": test_file},
            context=ADMIN_CTX,
        )
        assert isinstance(read_result, ToolResult)
        assert read_result.success is True
        assert "Hello NEXUS" in read_result.data["content"]


class TestJsonTools:
    def test_register(self):
        from nexus.tools.connectors.json_tool import create_json_tools
        registry = ToolRegistry()
        create_json_tools(registry)
        assert "json_query" in registry._tools
        assert "json_format" in registry._tools

    @pytest.mark.asyncio
    async def test_json_query(self):
        from nexus.tools.connectors.json_tool import create_json_tools
        registry = ToolRegistry()
        create_json_tools(registry)
        result = await registry.execute(
            "json_query",
            {"data": '{"user": {"name": "Alice", "age": 30}}', "path": "user.name"},
            context=ADMIN_CTX,
        )
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.data["result"] == "Alice"

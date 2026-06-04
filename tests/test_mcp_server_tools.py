"""MCP Server Tools 测试 — 补充覆盖 NexusMCPServer 的 Tool 注册和执行路径.

覆盖:
- server 初始化 (name, tool_registry)
- _register_tools / refresh_tools 方法
- _add_tool 方法
- run / run_async 方法（mock transport）
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.mcp.server import NexusMCPServer
from nexus.tools.registry import Tool, ToolRegistry, ToolType, ToolResult


class TestNexusMCPServerInit:
    """测试 NexusMCPServer 初始化."""

    def test_server_init_with_default_name(self):
        """默认名称为 'nexus'."""
        registry = MagicMock(spec=ToolRegistry)
        server = NexusMCPServer(registry)
        assert server._name == "nexus"

    def test_server_init_with_custom_name(self):
        """自定义名称."""
        registry = MagicMock(spec=ToolRegistry)
        server = NexusMCPServer(registry, name="custom-mcp")
        assert server._name == "custom-mcp"

    def test_server_init_creates_fastmcp(self):
        """初始化时创建 FastMCP 实例."""
        registry = MagicMock(spec=ToolRegistry)
        server = NexusMCPServer(registry, name="test")
        assert server.mcp is not None
        assert server.tool_registry is registry
        assert server._registered_tools == set()


class TestNexusMCPServerRegisterTools:
    """测试 _register_tools 和 refresh_tools."""

    def test_register_tools_populates_registered_set(self):
        """_register_tools 应在注册后填充 _registered_tools."""
        registry = ToolRegistry()
        registry.register(
            Tool(name="tool_a", description="A", type=ToolType.PYTHON, config={})
        )
        registry.register(
            Tool(name="tool_b", description="B", type=ToolType.PYTHON, config={})
        )

        server = NexusMCPServer(registry, name="test")
        server._register_tools()

        assert "tool_a" in server._registered_tools
        assert "tool_b" in server._registered_tools

    def test_register_tools_skips_already_registered(self):
        """已注册的 Tool 不应重复注册."""
        registry = ToolRegistry()
        registry.register(
            Tool(name="only_tool", description="Only", type=ToolType.PYTHON, config={})
        )

        server = NexusMCPServer(registry, name="test")
        server._register_tools()
        first_count = len(server._registered_tools)
        server._register_tools()  # 第二次调用

        assert len(server._registered_tools) == first_count

    def test_refresh_tools_calls_register(self):
        """refresh_tools 应调用 _register_tools."""
        registry = ToolRegistry()
        registry.register(
            Tool(name="t1", description="T1", type=ToolType.PYTHON, config={})
        )

        server = NexusMCPServer(registry, name="test")
        # refresh_tools 内部调用 _register_tools
        server.refresh_tools()
        assert "t1" in server._registered_tools

    def test_register_tools_with_missing_tool_def(self):
        """list_tools() 返回的 Tool 在 get_tool() 中不存在时应跳过."""
        registry = MagicMock(spec=ToolRegistry)
        registry.list_tools = MagicMock(
            return_value=[MagicMock(name="ghost_tool")]
        )
        registry.get_tool = MagicMock(return_value=None)  # 工具定义不存在

        server = NexusMCPServer(registry, name="test")
        server._register_tools()

        # 不应注册任何工具
        assert len(server._registered_tools) == 0


class TestNexusMCPServerAddTool:
    """测试 _add_tool 方法."""

    def test_add_tool_calls_fastmcp(self):
        """_add_tool 应调用 FastMCP.add_tool 注册 handler."""
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="compute",
                description="Do math",
                type=ToolType.PYTHON,
                config={},
                schema={"type": "object", "properties": {"expr": {"type": "string"}}},
            )
        )

        server = NexusMCPServer(registry, name="test")
        with patch.object(server.mcp, "add_tool") as mock_add:
            server._add_tool("compute", "Do math", {"type": "object"})

        mock_add.assert_called_once()
        kwargs = mock_add.call_args.kwargs
        assert kwargs["name"] == "compute"
        assert kwargs["description"] == "Do math"


class TestNexusMCPServerRun:
    """测试 run 和 run_async 方法."""

    def test_run_registers_tools_before_start(self):
        """run 方法应在启动前注册工具."""
        registry = ToolRegistry()
        registry.register(
            Tool(name="tool_x", description="X", type=ToolType.PYTHON, config={})
        )

        server = NexusMCPServer(registry, name="test")

        with patch.object(server.mcp, "run") as mock_run:
            server.run(transport="stdio", port=9999, host="127.0.0.1")

        assert "tool_x" in server._registered_tools
        assert server.mcp.settings.port == 9999
        assert server.mcp.settings.host == "127.0.0.1"

    @pytest.mark.asyncio
    async def test_run_async_registers_tools(self):
        """run_async 应在启动前注册工具（只测注册，不启动服务器）."""
        registry = ToolRegistry()
        registry.register(
            Tool(name="tool_y", description="Y", type=ToolType.PYTHON, config={})
        )

        server = NexusMCPServer(registry, name="test")

        # SseServerTransport 在 run_async 内局部导入,
        # 需要 patch mcp.server.sse 上的模块路径
        with patch.object(server, "_register_tools") as mock_register:
            with patch("mcp.server.sse.SseServerTransport", side_effect=RuntimeError("stop early")):
                with pytest.raises(RuntimeError):
                    await server.run_async(transport="sse", port=8777)
            mock_register.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_async_non_sse_raises_value_error(self):
        """run_async 对非 'sse' transport 应抛出 ValueError (异步验证)."""
        registry = ToolRegistry()
        server = NexusMCPServer(registry, name="test")

        with pytest.raises(ValueError, match="Async run only supports 'sse'"):
            await server.run_async(transport="stdio")

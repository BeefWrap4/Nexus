"""MCP Client integration tests — Phase 5.

Covers:
- MCPClientManager: attach_registry, connect mock, tool discovery, namespace isolation
- ToolRegistry._execute_mcp: delegates to MCPClientManager
- MCPConnection: lifecycle, list_tools, call_tool
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.mcp.client import (
    MCPClientManager,
    MCPConnection,
    MCPServerConnection,
    get_mcp_client_manager,
    set_mcp_client_manager,
)
from nexus.tools.registry import Tool, ToolRegistry, ToolResult, ToolType


# -----------------------------------------------------------------------------
# Phase 5.1: MCPClientManager
# -----------------------------------------------------------------------------

class TestMCPClientManager:
    """Test MCP Client Manager functionality."""

    def test_attach_registry(self):
        """Should attach ToolRegistry via constructor or method."""
        registry = ToolRegistry()
        mgr = MCPClientManager(tool_registry=registry)
        assert mgr._tool_registry is registry

        mgr2 = MCPClientManager()
        assert mgr2._tool_registry is None
        mgr2.attach_registry(registry)
        assert mgr2._tool_registry is registry

    @pytest.mark.asyncio
    async def test_discover_and_register_namespace_isolation(self):
        """Tools should be registered with namespace prefix {server}__{tool}."""
        registry = ToolRegistry()
        mgr = MCPClientManager(tool_registry=registry)

        # Mock connection with tools
        mock_conn = MagicMock()
        mock_conn._tools = []
        mock_conn.list_tools = AsyncMock(
            return_value=[
                {
                    "name": "read_file",
                    "description": "Read a file",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                },
                {
                    "name": "list_directory",
                    "description": "List directory contents",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                },
            ]
        )

        discovered = await mgr._discover_and_register("filesystem", mock_conn)

        assert len(discovered) == 2
        assert "filesystem__read_file" in discovered
        assert "filesystem__list_directory" in discovered

        # Verify tools are in registry
        tool1 = registry.get_tool("filesystem__read_file")
        assert tool1 is not None
        assert tool1.type == ToolType.MCP
        assert tool1.config["mcp_server"] == "filesystem"
        assert tool1.config["mcp_tool_name"] == "read_file"

    @pytest.mark.asyncio
    async def test_disconnect_unregisters_tools(self):
        """Disconnect should unregister all tools from that server."""
        registry = ToolRegistry()
        mgr = MCPClientManager(tool_registry=registry)

        # Register some tools
        registry.register(Tool(name="fs__read", description="", type=ToolType.MCP, config={}))
        registry.register(Tool(name="fs__write", description="", type=ToolType.MCP, config={}))
        registry.register(Tool(name="other__tool", description="", type=ToolType.HTTP, config={}))

        # Mock connection
        mock_conn = MagicMock()
        mock_conn.disconnect = AsyncMock()
        mgr._connections["fs"] = mock_conn

        await mgr.disconnect("fs")

        assert registry.get_tool("fs__read") is None
        assert registry.get_tool("fs__write") is None
        assert registry.get_tool("other__tool") is not None

    @pytest.mark.asyncio
    async def test_call_tool_delegates_to_connection(self):
        """call_tool should find connection and delegate."""
        mgr = MCPClientManager()

        mock_conn = MagicMock()
        mock_conn.call_tool = AsyncMock(return_value={"content": "hello", "isError": False})
        mgr._connections["test"] = mock_conn

        result = await mgr.call_tool("test", "my_tool", {"arg": 1})
        assert result["content"] == "hello"
        mock_conn.call_tool.assert_called_once_with("my_tool", {"arg": 1})

    def test_list_connections(self):
        """list_connections should return all active connections metadata."""
        mgr = MCPClientManager()

        mock_conn = MagicMock()
        mock_conn.conn = MCPServerConnection(
            name="test", transport="sse", url="http://localhost:3001/sse"
        )
        mock_conn.connected = True
        mock_conn._tools = ["tool1", "tool2"]
        mgr._connections["test"] = mock_conn

        conns = mgr.list_connections()
        assert len(conns) == 1
        assert conns[0]["name"] == "test"
        assert conns[0]["transport"] == "sse"
        assert conns[0]["connected"] is True
        assert conns[0]["tools"] == ["tool1", "tool2"]


# -----------------------------------------------------------------------------
# MCPConnection lifecycle
# -----------------------------------------------------------------------------

class TestMCPConnection:
    """Test MCPConnection wrapper."""

    @pytest.mark.asyncio
    async def test_list_tools_parses_result(self):
        """list_tools should parse MCP SDK result into dict list."""
        conn = MCPConnection(
            MCPServerConnection(name="test", transport="sse", url="http://localhost/sse")
        )

        # Mock session
        mock_session = MagicMock()
        mock_tool = MagicMock()
        mock_tool.name = "read_file"
        mock_tool.description = "Read file"
        mock_tool.inputSchema = {"type": "object"}

        mock_session.list_tools = AsyncMock(
            return_value=MagicMock(tools=[mock_tool])
        )
        conn.session = mock_session

        tools = await conn.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "read_file"
        assert tools[0]["description"] == "Read file"

    @pytest.mark.asyncio
    async def test_call_tool_extracts_text_content(self):
        """call_tool should extract text from MCP result content."""
        conn = MCPConnection(
            MCPServerConnection(name="test", transport="sse", url="http://localhost/sse")
        )

        mock_session = MagicMock()
        text_item = MagicMock()
        text_item.text = "Hello from MCP"
        result_mock = MagicMock()
        result_mock.content = [text_item]
        result_mock.isError = False

        mock_session.call_tool = AsyncMock(return_value=result_mock)
        conn.session = mock_session

        result = await conn.call_tool("my_tool", {"arg": 1})
        assert result["content"] == "Hello from MCP"
        assert result["isError"] is False

    def test_not_connected_without_session(self):
        """connected should be False when session is None."""
        conn = MCPConnection(
            MCPServerConnection(name="test", transport="sse", url="http://localhost/sse")
        )
        assert conn.connected is False


# -----------------------------------------------------------------------------
# ToolRegistry._execute_mcp integration
# -----------------------------------------------------------------------------

class TestToolRegistryExecuteMCP:
    """Test ToolRegistry delegates MCP execution to MCPClientManager."""

    @pytest.mark.asyncio
    async def test_execute_mcp_success(self):
        """_execute_mcp should delegate to MCPClientManager and return ToolResult."""
        registry = ToolRegistry()

        # Mock MCPClientManager
        mock_mgr = MagicMock()
        mock_mgr.call_tool = AsyncMock(
            return_value={"content": "MCP result", "isError": False}
        )
        set_mcp_client_manager(mock_mgr)

        tool = Tool(
            name="fs__read",
            description="Read file",
            type=ToolType.MCP,
            config={"mcp_server": "fs", "mcp_tool_name": "read"},
        )

        result = await registry._execute_mcp(tool, {"path": "/tmp/test"}, {})

        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.data == "MCP result"
        mock_mgr.call_tool.assert_called_once_with("fs", "read", {"path": "/tmp/test"})

    @pytest.mark.asyncio
    async def test_execute_mcp_with_error(self):
        """_execute_mcp should handle MCP errors gracefully."""
        registry = ToolRegistry()

        mock_mgr = MagicMock()
        mock_mgr.call_tool = AsyncMock(
            return_value={"content": "Error occurred", "isError": True}
        )
        set_mcp_client_manager(mock_mgr)

        tool = Tool(
            name="fs__read",
            description="Read file",
            type=ToolType.MCP,
            config={"mcp_server": "fs", "mcp_tool_name": "read"},
        )

        result = await registry._execute_mcp(tool, {"path": "/tmp/test"}, {})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_mcp_missing_config(self):
        """_execute_mcp should fail if config is incomplete."""
        registry = ToolRegistry()

        tool = Tool(
            name="bad_tool",
            description="Bad tool",
            type=ToolType.MCP,
            config={},  # Missing mcp_server and mcp_tool_name
        )

        result = await registry._execute_mcp(tool, {}, {})
        assert result.success is False
        assert "Invalid MCP tool config" in result.error

    @pytest.mark.asyncio
    async def test_execute_mcp_exception(self):
        """_execute_mcp should catch exceptions and return failed ToolResult."""
        registry = ToolRegistry()

        mock_mgr = MagicMock()
        mock_mgr.call_tool = AsyncMock(side_effect=RuntimeError("Connection lost"))
        set_mcp_client_manager(mock_mgr)

        tool = Tool(
            name="fs__read",
            description="Read file",
            type=ToolType.MCP,
            config={"mcp_server": "fs", "mcp_tool_name": "read"},
        )

        result = await registry._execute_mcp(tool, {"path": "/tmp/test"}, {})
        assert result.success is False
        assert "Connection lost" in result.error


# -----------------------------------------------------------------------------
# Global singleton
# -----------------------------------------------------------------------------

class TestMCPSingleton:
    """Test global MCPClientManager singleton."""

    def test_get_mcp_client_manager_creates_singleton(self):
        """get_mcp_client_manager should create and return singleton."""
        set_mcp_client_manager(None)
        mgr1 = get_mcp_client_manager()
        mgr2 = get_mcp_client_manager()
        assert mgr1 is mgr2

    def test_get_mcp_client_manager_attaches_registry(self):
        """get_mcp_client_manager should attach registry if provided."""
        set_mcp_client_manager(None)
        registry = ToolRegistry()
        mgr = get_mcp_client_manager(tool_registry=registry)
        assert mgr._tool_registry is registry

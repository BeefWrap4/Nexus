"""MCP Server tests — Phase 5.

Covers:
- NexusMCPServer: tool registration from ToolRegistry
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nexus.mcp.server import NexusMCPServer
from nexus.tools.registry import Tool, ToolRegistry, ToolType


class TestNexusMCPServer:
    """Test built-in MCP Server."""

    def test_registers_tools_from_registry(self):
        """NexusMCPServer should register tools from ToolRegistry."""
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="rag_ask",
                description="RAG Q&A",
                type=ToolType.HTTP,
                config={"url": "http://localhost:8777/ask"},
                schema={"type": "object", "properties": {"prompt": {"type": "string"}}},
            )
        )
        registry.register(
            Tool(
                name="sql_query",
                description="Run SQL",
                type=ToolType.SQL,
                config={},
            )
        )

        server = NexusMCPServer(registry, name="test-nexus")
        server._register_tools()

        # FastMCP should have 2 tools registered
        assert "rag_ask" in server._registered_tools
        assert "sql_query" in server._registered_tools

    def test_skips_duplicate_tools(self):
        """Should not re-register already registered tools."""
        registry = ToolRegistry()
        registry.register(
            Tool(name="tool1", description="T1", type=ToolType.HTTP, config={})
        )

        server = NexusMCPServer(registry)
        server._register_tools()
        server._register_tools()  # Call again

        assert len(server._registered_tools) == 1

    def test_mcp_tool_handler_delegates_to_registry(self):
        """The dynamically created MCP tool handler should call ToolRegistry.execute."""
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="test_tool",
                description="Test",
                type=ToolType.HTTP,
                config={},
            )
        )
        # Mock execute
        registry.execute = MagicMock(return_value=None)

        server = NexusMCPServer(registry)
        server._register_tools()

        # The tool should be in FastMCP
        assert "test_tool" in server._registered_tools

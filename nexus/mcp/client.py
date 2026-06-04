"""MCP Client Manager.

Connect to external MCP Servers via stdio or SSE,
discover tools automatically, and register them to NEXUS ToolRegistry.

Phase 5.1: MCP Client Integration
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from nexus.tools.registry import Tool, ToolRegistry, ToolResult, ToolType


@dataclass
class MCPServerConnection:
    """MCP Server connection configuration."""

    name: str
    transport: str  # "stdio" | "sse"
    command: str | None = None  # stdio: e.g. "python"
    args: list[str] = field(default_factory=list)  # stdio: e.g. ["-m", "mcp_server"]
    url: str | None = None  # sse: e.g. "http://localhost:3001/sse"
    env: dict[str, str] = field(default_factory=dict)


class MCPConnection:
    """Single MCP Server connection wrapper.

    Manages the lifecycle of a ClientSession using AsyncExitStack
    to keep the underlying transport alive.
    """

    def __init__(self, conn: MCPServerConnection):
        self.conn = conn
        self.session = None
        self._exit_stack: AsyncExitStack | None = None
        self._tools: list[str] = []

    async def connect(self) -> None:
        """Establish connection to the MCP Server."""
        from mcp import ClientSession

        self._exit_stack = AsyncExitStack()

        if self.conn.transport == "stdio":
            from mcp.client.stdio import stdio_client
            from mcp.client.stdio import StdioServerParameters

            params = StdioServerParameters(
                command=self.conn.command or "",
                args=self.conn.args,
                env=self.conn.env if self.conn.env else None,
            )
            read_stream, write_stream = await self._exit_stack.enter_async_context(
                stdio_client(params)
            )
        elif self.conn.transport == "sse":
            from mcp.client.sse import sse_client

            if not self.conn.url:
                raise ValueError("SSE transport requires 'url'")
            read_stream, write_stream = await self._exit_stack.enter_async_context(
                sse_client(self.conn.url)
            )
        else:
            raise ValueError(f"Unsupported transport: {self.conn.transport}")

        session = ClientSession(read_stream, write_stream)
        self.session = await self._exit_stack.enter_async_context(session)
        await self.session.initialize()

    async def disconnect(self) -> None:
        """Close connection and cleanup resources."""
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
        self.session = None

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the MCP Server."""
        if not self.session:
            raise RuntimeError("MCP connection not established")

        result = await self.session.list_tools()
        tools = []
        for tool in result.tools:
            tools.append({
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": tool.inputSchema,
            })
        return tools

    async def call_tool(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP Server."""
        if not self.session:
            raise RuntimeError("MCP connection not established")

        result = await self.session.call_tool(tool_name, arguments=params)
        # Extract text content from result
        texts = []
        for item in result.content:
            if hasattr(item, "text"):
                texts.append(item.text)
        return {
            "content": "\n".join(texts),
            "isError": result.isError,
        }

    @property
    def connected(self) -> bool:
        return self.session is not None


class MCPClientManager:
    """MCP Client Manager.

    Manages multiple external MCP Server connections,
    auto-discovers tools, and registers them to ToolRegistry.
    """

    def __init__(self, tool_registry: ToolRegistry | None = None):
        self._connections: dict[str, MCPConnection] = {}
        self._tool_registry = tool_registry

    def attach_registry(self, tool_registry: ToolRegistry) -> None:
        """Attach a ToolRegistry (for late binding)."""
        self._tool_registry = tool_registry

    async def connect_stdio(self, conn: MCPServerConnection) -> list[str]:
        """Connect to a local MCP Server via stdio.

        Returns:
            List of discovered tool names (with namespace prefix).
        """
        connection = MCPConnection(conn)
        await connection.connect()
        self._connections[conn.name] = connection
        return await self._discover_and_register(conn.name, connection)

    async def connect_sse(self, conn: MCPServerConnection) -> list[str]:
        """Connect to a remote MCP Server via SSE.

        Returns:
            List of discovered tool names (with namespace prefix).
        """
        connection = MCPConnection(conn)
        await connection.connect()
        self._connections[conn.name] = connection
        return await self._discover_and_register(conn.name, connection)

    async def _discover_and_register(
        self, name: str, connection: MCPConnection
    ) -> list[str]:
        """Discover tools and register them to ToolRegistry."""
        tools = await connection.list_tools()
        registered = []

        if not self._tool_registry:
            return registered

        for tool in tools:
            # Namespace isolation: {server}__{tool}
            namespaced_name = f"{name}__{tool['name']}"
            self._tool_registry.register(
                Tool(
                    name=namespaced_name,
                    description=tool["description"],
                    type=ToolType.MCP,
                    config={
                        "mcp_server": name,
                        "mcp_tool_name": tool["name"],
                    },
                    schema=tool.get("inputSchema", {"type": "object", "properties": {}}),
                )
            )
            registered.append(namespaced_name)
            connection._tools.append(tool["name"])

        return registered

    async def call_tool(
        self, conn_name: str, tool_name: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Call a tool on the specified MCP Server."""
        connection = self._connections.get(conn_name)
        if not connection:
            raise RuntimeError(f"MCP connection '{conn_name}' not found")
        return await connection.call_tool(tool_name, params)

    async def disconnect(self, name: str) -> None:
        """Disconnect from an MCP Server and unregister its tools."""
        connection = self._connections.pop(name, None)
        if connection:
            # Unregister all tools from this server
            if self._tool_registry:
                prefix = f"{name}__"
                for tool_name in list(self._tool_registry._tools.keys()):
                    if tool_name.startswith(prefix):
                        self._tool_registry.unregister(tool_name)
            await connection.disconnect()

    def list_connections(self) -> list[dict[str, Any]]:
        """List all active MCP connections."""
        return [
            {
                "name": conn.conn.name,
                "transport": conn.conn.transport,
                "url": conn.conn.url,
                "command": conn.conn.command,
                "connected": conn.connected,
                "tools": conn._tools,
            }
            for conn in self._connections.values()
        ]

    def get_connection(self, name: str) -> MCPConnection | None:
        """Get a connection by name."""
        return self._connections.get(name)


# ---------------------------------------------------------------------------
# Global MCPClientManager singleton
# ---------------------------------------------------------------------------
# 设计意图：进程级单例，在 API 进程和 ARQ Worker 之间共享 MCP 连接管理。
# 线程安全注意事项：
#   - 此单例管理 MCP 服务器发现的元数据，不存储租户特定数据
#   - 每次工具调用时按租户/用户隔离创建独立的 MCP sessions
#   - 全局初始化在 app startup 阶段完成，运行时仅读取注册信息
#   - 如需测试隔离，使用 set_mcp_client_manager() 替换
# ---------------------------------------------------------------------------
_global_mcp_client_manager: MCPClientManager | None = None


def get_mcp_client_manager(tool_registry: ToolRegistry | None = None) -> MCPClientManager:
    """Get global MCPClientManager singleton.

    Late-binding: if tool_registry is provided, it will be attached
    to the manager (useful when called before ToolRegistry is ready).
    """
    global _global_mcp_client_manager
    if _global_mcp_client_manager is None:
        _global_mcp_client_manager = MCPClientManager(tool_registry=tool_registry)
    elif tool_registry is not None:
        _global_mcp_client_manager.attach_registry(tool_registry)
    return _global_mcp_client_manager


def set_mcp_client_manager(manager: MCPClientManager) -> None:
    """Set global MCPClientManager (for testing)."""
    global _global_mcp_client_manager
    _global_mcp_client_manager = manager

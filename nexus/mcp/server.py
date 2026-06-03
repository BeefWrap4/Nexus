"""NEXUS built-in MCP Server.

Expose NEXUS ToolRegistry tools as a standard MCP Server
via SSE transport, so Claude Desktop / Cursor can connect.

Phase 5.2: Built-in MCP Server
"""

from __future__ import annotations

from typing import Any

from nexus.tools.registry import ToolRegistry


class NexusMCPServer:
    """NEXUS built-in MCP Server.

    Uses FastMCP to expose NEXUS ToolRegistry tools as standard MCP tools.
    Supports SSE transport for compatibility with Claude Desktop, Cursor, etc.
    """

    def __init__(self, tool_registry: ToolRegistry, name: str = "nexus"):
        from mcp.server.fastmcp import FastMCP

        self.mcp = FastMCP(name)
        self.tool_registry = tool_registry
        self._name = name
        self._registered_tools: set[str] = set()

    def _register_tools(self) -> None:
        """Register all tools from ToolRegistry as MCP tools."""
        for tool_info in self.tool_registry.list_tools():
            tool_def = self.tool_registry.get_tool(tool_info.name)
            if not tool_def or tool_info.name in self._registered_tools:
                continue

            self._add_tool(tool_info.name, tool_info.description, tool_def.schema)
            self._registered_tools.add(tool_info.name)

    def _add_tool(self, name: str, description: str, schema: dict[str, Any]) -> None:
        """Dynamically add a single tool to the MCP server.

        We create a closure that captures the tool name and delegates
        to the ToolRegistry for execution.
        """
        registry = self.tool_registry

        # Build function signature from schema for FastMCP introspection
        async def mcp_tool_handler(**kwargs: Any) -> str | dict[str, Any]:
            """MCP tool handler — delegates to ToolRegistry."""
            result = await registry.execute(
                tool_name=name,
                params=kwargs,
            )
            if result.success:
                if isinstance(result.data, str):
                    return result.data
                return result.data if result.data is not None else {"status": "ok"}
            return {"error": result.error}

        # Update metadata for FastMCP
        mcp_tool_handler.__name__ = name
        mcp_tool_handler.__doc__ = description

        self.mcp.add_tool(
            fn=mcp_tool_handler,
            name=name,
            description=description,
        )

    def refresh_tools(self) -> None:
        """Refresh tool registration (call after ToolRegistry changes)."""
        self._register_tools()

    def run(self, transport: str = "sse", port: int = 8766, host: str = "0.0.0.0") -> None:
        """Start the MCP Server.

        Args:
            transport: "sse" or "stdio"
            port: Port for SSE transport
            host: Host for SSE transport
        """
        self._register_tools()
        self.mcp.settings.port = port
        self.mcp.settings.host = host
        self.mcp.run(transport=transport)

    async def run_async(
        self, transport: str = "sse", port: int = 8766, host: str = "0.0.0.0"
    ) -> None:
        """Async version for integration with FastAPI lifespan."""
        import asyncio

        self._register_tools()
        self.mcp.settings.port = port
        self.mcp.settings.host = host

        if transport == "sse":
            from mcp.server.sse import SseServerTransport
            from starlette.applications import Starlette
            from starlette.routing import Route

            sse = SseServerTransport("/messages/")

            async def handle_sse(request):
                async with sse.connect_session(
                    request.scope, request.receive, request._send
                ) as streams:
                    await self.mcp._mcp_server.run(
                        streams[0], streams[1], self.mcp._mcp_server.create_initialization_options()
                    )

            async def handle_messages(request):
                await sse.handle_post_message(request.scope, request.receive, request._send)

            starlette_app = Starlette(
                debug=False,
                routes=[
                    Route("/sse", endpoint=handle_sse),
                    Route("/messages/", endpoint=handle_messages, methods=["POST"]),
                ],
            )

            import uvicorn
            config = uvicorn.Config(starlette_app, host=host, port=port, log_level="info")
            server = uvicorn.Server(config)
            await server.serve()
        else:
            raise ValueError(f"Async run only supports 'sse', got '{transport}'")

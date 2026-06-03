"""MCP Server connection management API.

REST API for registering, listing, and disconnecting MCP Server connections.

Phase 5.3: MCP Connection Management API
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from nexus.mcp.client import MCPServerConnection, get_mcp_client_manager
from nexus.security.auth import get_current_user
from nexus.tools.registry import get_tool_registry

router = APIRouter()


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------

class MCPServerCreate(BaseModel):
    """Request model for creating an MCP Server connection."""

    name: str = Field(..., description="Unique connection name")
    transport: str = Field(..., description="Transport type: 'stdio' or 'sse'")
    command: str | None = Field(None, description="Command for stdio transport")
    args: list[str] = Field(default_factory=list, description="Arguments for stdio transport")
    url: str | None = Field(None, description="URL for SSE transport")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables")


class MCPServerResponse(BaseModel):
    """Response model for MCP Server connection."""

    name: str
    transport: str
    command: str | None = None
    url: str | None = None
    status: str
    tools_discovered: list[str] = Field(default_factory=list)


class MCPConnectionList(BaseModel):
    """Response model for listing connections."""

    connections: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@router.post("/connections", response_model=MCPServerResponse)
async def create_connection(
    data: MCPServerCreate,
    current_user: dict = Depends(get_current_user),
):
    """Register and connect to an MCP Server.

    Discovers tools automatically and registers them to the global ToolRegistry.
    """
    mcp_mgr = get_mcp_client_manager()
    # Ensure tool_registry is attached
    if mcp_mgr._tool_registry is None:
        mcp_mgr.attach_registry(get_tool_registry())

    # Check if connection already exists
    if mcp_mgr.get_connection(data.name):
        raise HTTPException(status_code=409, detail=f"Connection '{data.name}' already exists")

    conn = MCPServerConnection(
        name=data.name,
        transport=data.transport,
        command=data.command,
        args=data.args,
        url=data.url,
        env=data.env,
    )

    try:
        if data.transport == "stdio":
            discovered = await mcp_mgr.connect_stdio(conn)
        elif data.transport == "sse":
            discovered = await mcp_mgr.connect_sse(conn)
        else:
            raise HTTPException(
                status_code=400, detail=f"Unsupported transport: {data.transport}"
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect: {str(e)}")

    return MCPServerResponse(
        name=data.name,
        transport=data.transport,
        command=data.command,
        url=data.url,
        status="connected",
        tools_discovered=discovered,
    )


@router.get("/connections", response_model=MCPConnectionList)
async def list_connections(current_user: dict = Depends(get_current_user)):
    """List all active MCP Server connections."""
    mcp_mgr = get_mcp_client_manager()
    connections = mcp_mgr.list_connections()
    return MCPConnectionList(connections=connections)


@router.get("/connections/{name}")
async def get_connection(
    name: str,
    current_user: dict = Depends(get_current_user),
):
    """Get details of a specific MCP Server connection."""
    mcp_mgr = get_mcp_client_manager()
    conn = mcp_mgr.get_connection(name)
    if not conn:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    return {
        "name": conn.conn.name,
        "transport": conn.conn.transport,
        "url": conn.conn.url,
        "command": conn.conn.command,
        "args": conn.conn.args,
        "connected": conn.connected,
        "tools": conn._tools,
    }


@router.delete("/connections/{name}")
async def disconnect_connection(
    name: str,
    current_user: dict = Depends(get_current_user),
):
    """Disconnect from an MCP Server and unregister its tools."""
    mcp_mgr = get_mcp_client_manager()
    conn = mcp_mgr.get_connection(name)
    if not conn:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    await mcp_mgr.disconnect(name)
    return {"name": name, "status": "disconnected"}


@router.post("/connections/{name}/tools/{tool_name}")
async def call_mcp_tool(
    name: str,
    tool_name: str,
    params: dict[str, Any] | None = None,
    current_user: dict = Depends(get_current_user),
):
    """Directly call a tool on an MCP Server (for testing/debugging).

    Note: Normally tools are called through ToolRegistry.execute()
    which routes to MCPClientManager automatically.
    """
    mcp_mgr = get_mcp_client_manager()
    conn = mcp_mgr.get_connection(name)
    if not conn:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    try:
        result = await mcp_mgr.call_tool(name, tool_name, params or {})
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tool call failed: {str(e)}")

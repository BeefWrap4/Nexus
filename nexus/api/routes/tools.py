"""工具路由."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import get_db, get_tenant_db
from nexus.security.auth import get_current_user
from nexus.services.tool import ToolService

router = APIRouter()

tool_service = ToolService()


class ToolCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    type: str = "http"  # http / sql / python / mcp
    config: dict = Field(default_factory=dict)
    input_schema: dict = Field(default_factory=dict, alias="schema")
    auth_config: dict = Field(default_factory=dict)


class ToolResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    description: str
    type: str
    status: str
    created_at: str
    input_schema: dict = Field(default_factory=dict, alias="schema")
    source: str = "db"  # db / registry


def _to_response(tool) -> dict:
    return {
        "id": str(tool.id),
        "name": tool.name,
        "description": tool.description or "",
        "type": tool.type,
        "status": tool.status or "active",
        "created_at": tool.created_at.isoformat() if tool.created_at else "",
        "schema": tool.schema if hasattr(tool, "schema") else {},
        "source": "db",
    }


@router.get("/")
async def list_tools(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
):
    """列出工具（合并 DB 工具和内存 RAG Tools）."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))

    # 1. DB 中的工具
    db_items, _ = await tool_service.list(db, tenant_id)
    results = [_to_response(t) for t in db_items]

    # 2. 内存 ToolRegistry 中的工具（RAG Tools 等）
    from nexus.tools.registry import get_tool_registry

    registry = get_tool_registry()
    registry_tools = registry.list_tools(context={"tenant_id": str(tenant_id)})

    for tool_info in registry_tools:
        tool_def = registry.get_tool(tool_info.name)
        if tool_def:
            results.append({
                "id": tool_info.name,  # 内存工具用 name 作为 ID
                "name": tool_info.name,
                "description": tool_info.description,
                "type": tool_def.type.value,
                "status": "active",
                "created_at": "",
                "schema": tool_info.schema,
                "source": "registry",
            })

    return results


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_tool(
    data: ToolCreate,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
):
    """注册工具."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    tool = await tool_service.create(
        db,
        data={
            "name": data.name,
            "description": data.description,
            "type": data.type,
            "config": data.config,
            "schema": data.input_schema,
            "auth_config": data.auth_config,
        },
        tenant_id=tenant_id,
    )

    return _to_response(tool)


@router.get("/{tool_id}")
async def get_tool(
    tool_id: UUID,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
):
    """获取工具."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    tool = await tool_service.get(db, tool_id, tenant_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    return _to_response(tool)


@router.put("/{tool_id}")
async def update_tool(
    tool_id: UUID,
    data: ToolCreate,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
):
    """更新工具."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    tool = await tool_service.update(
        db,
        tool_id,
        data=data.model_dump(by_alias=True),
        tenant_id=tenant_id,
    )
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    return _to_response(tool)


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(
    tool_id: UUID,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
):
    """删除工具."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    ok = await tool_service.delete(db, tool_id, tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Tool not found")

    return None


@router.post("/{tool_id}/test")
async def test_tool(
    tool_id: UUID,
    params: dict,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
):
    """测试工具."""
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    tool = await tool_service.get(db, tool_id, tenant_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    return {
        "success": True,
        "tool_name": tool.name,
        "tool_type": tool.type,
        "params": params,
        "result": "Tool test placeholder",
    }

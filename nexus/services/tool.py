"""Tool服务层.

提供Tool注册的CRUD操作。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models import Tool
from nexus.services.base import BaseService


class ToolService(BaseService[Tool]):
    """工具注册Service."""

    def __init__(self):
        super().__init__(Tool)

    async def get_by_name(
        self,
        session: AsyncSession,
        name: str,
        tenant_id: UUID,
    ) -> Tool | None:
        """根据名称获取工具.

        Args:
            session: 数据库会话
            name: 工具名称
            tenant_id: 租户ID

        Returns:
            Tool实例，不存在则返回None
        """
        stmt = select(Tool).where(
            Tool.name == name,
            Tool.tenant_id == tenant_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 100,
        filters: dict[str, Any] | None = None,
    ) -> tuple[list[Tool], int]:
        """分页列表查询，支持按type和status过滤."""
        return await super().list(session, tenant_id, skip, limit, filters)

    async def update_status(
        self,
        session: AsyncSession,
        tool_id: UUID,
        tenant_id: UUID,
        status: str,
    ) -> Tool | None:
        """更新工具状态.

        Args:
            session: 数据库会话
            tool_id: 工具ID
            tenant_id: 租户ID
            status: 新状态 (active / inactive / deprecated)

        Returns:
            更新后的Tool实例
        """
        tool = await self.get(session, tool_id, tenant_id)
        if tool is None:
            return None

        tool.status = status
        session.add(tool)
        await session.flush()
        await session.refresh(tool)
        return tool

    async def list_by_type(
        self,
        session: AsyncSession,
        tool_type: str,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Tool], int]:
        """按工具类型查询.

        Args:
            session: 数据库会话
            tool_type: 工具类型 (http / sql / python / mcp)
            tenant_id: 租户ID
            skip: 偏移量
            limit: 每页数量

        Returns:
            (工具列表, 总数量)
        """
        filters = {"type": tool_type}
        return await self.list(session, tenant_id, skip, limit, filters)

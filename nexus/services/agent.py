"""Agent服务层.

提供Agent配置的CRUD操作。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models import Agent
from nexus.services.base import BaseService


class AgentService(BaseService[Agent]):
    """Agent配置Service."""

    def __init__(self):
        super().__init__(Agent)

    async def get_by_name(
        self,
        session: AsyncSession,
        name: str,
        tenant_id: UUID,
    ) -> Agent | None:
        """根据名称获取Agent.

        Args:
            session: 数据库会话
            name: Agent名称
            tenant_id: 租户ID

        Returns:
            Agent实例，不存在则返回None
        """
        stmt = select(Agent).where(
            Agent.name == name,
            Agent.tenant_id == tenant_id,
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
    ) -> tuple[list[Agent], int]:
        """分页列表查询，支持按role过滤."""
        return await super().list(session, tenant_id, skip, limit, filters)

    async def update_tools(
        self,
        session: AsyncSession,
        agent_id: UUID,
        tenant_id: UUID,
        tools: list[str],
    ) -> Agent | None:
        """更新Agent的工具列表.

        Args:
            session: 数据库会话
            agent_id: Agent ID
            tenant_id: 租户ID
            tools: 工具名称列表

        Returns:
            更新后的Agent实例
        """
        agent = await self.get(session, agent_id, tenant_id)
        if agent is None:
            return None

        agent.tools = tools
        session.add(agent)
        await session.flush()
        await session.refresh(agent)
        await session.commit()
        return agent

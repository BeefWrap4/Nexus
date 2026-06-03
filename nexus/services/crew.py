"""Crew 团队 Service 层.

Phase 10: 多 Agent 协作增强
- CrewService: Crew CRUD + Agent 关联管理
- CrewRunService: Crew 执行记录管理
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models.crew import Crew, CrewAgent, CrewRun
from nexus.models.agent import Agent
from nexus.services.base import BaseService


class CrewService(BaseService[Crew]):
    """Crew 团队 Service."""

    def __init__(self):
        super().__init__(Crew)

    async def create(
        self,
        session: AsyncSession,
        data: dict[str, Any],
        tenant_id: UUID,
        user_id: UUID | None = None,
    ) -> Crew:
        """创建 Crew + 关联 Agent.

        data 格式:
        {
            "name": str,
            "description": str,
            "mode": str,
            "config": dict,
            "agent_ids": list[{"agent_id": UUID, "role_in_crew": str, "order_index": int}],
        }
        """
        agent_ids = data.pop("agent_ids", [])

        crew = await super().create(session, data, tenant_id, user_id)

        # 创建 Crew-Agent 关联
        for item in agent_ids:
            ca = CrewAgent(
                crew_id=crew.id,
                agent_id=item["agent_id"],
                role_in_crew=item.get("role_in_crew", "worker"),
                order_index=item.get("order_index", 0),
            )
            session.add(ca)

        await session.flush()
        # NOTE: 不在这里 commit，事务边界由调用方控制
        return crew

    async def get_with_agents(
        self,
        session: AsyncSession,
        crew_id: UUID,
        tenant_id: UUID,
    ) -> dict[str, Any] | None:
        """获取 Crew 详情（包含关联 Agent 列表）."""
        crew = await self.get(session, crew_id, tenant_id)
        if not crew:
            return None

        # 加载关联 Agent
        stmt = (
            select(CrewAgent, Agent)
            .join(Agent, CrewAgent.agent_id == Agent.id)
            .where(CrewAgent.crew_id == crew_id)
            .order_by(CrewAgent.order_index)
        )
        result = await session.execute(stmt)
        rows = result.all()

        agents = []
        for ca, agent in rows:
            agents.append({
                "id": str(agent.id),
                "name": agent.name,
                "role": agent.role,
                "role_in_crew": ca.role_in_crew,
                "order_index": ca.order_index,
            })

        return {
            "id": str(crew.id),
            "tenant_id": str(crew.tenant_id),
            "name": crew.name,
            "description": crew.description,
            "mode": crew.mode,
            "config": crew.config,
            "agents": agents,
            "created_at": crew.created_at.isoformat() if crew.created_at else None,
            "updated_at": crew.updated_at.isoformat() if crew.updated_at else None,
        }

    async def update(
        self,
        session: AsyncSession,
        crew_id: UUID,
        data: dict[str, Any],
        tenant_id: UUID,
    ) -> Crew | None:
        """更新 Crew + 关联 Agent."""
        agent_ids = data.pop("agent_ids", None)

        crew = await super().update(session, crew_id, data, tenant_id)
        if not crew:
            return None

        # 如果提供了 agent_ids，更新关联
        if agent_ids is not None:
            # 删除旧关联
            stmt = select(CrewAgent).where(
                CrewAgent.crew_id == crew_id,
            )
            result = await session.execute(stmt)
            for ca in result.scalars().all():
                await session.delete(ca)

            # 创建新关联
            for item in agent_ids:
                ca = CrewAgent(
                    crew_id=crew.id,
                    agent_id=item["agent_id"],
                    role_in_crew=item.get("role_in_crew", "worker"),
                    order_index=item.get("order_index", 0),
                )
                session.add(ca)

            await session.flush()
            # NOTE: 不在这里 commit，事务边界由调用方控制

        return crew

    async def delete(
        self,
        session: AsyncSession,
        crew_id: UUID,
        tenant_id: UUID,
    ) -> bool:
        """删除 Crew（级联删除 CrewAgent 和 CrewRun）."""
        return await super().delete(session, crew_id, tenant_id)


class CrewRunService(BaseService[CrewRun]):
    """Crew 执行记录 Service."""

    def __init__(self):
        super().__init__(CrewRun)

    async def create(
        self,
        session: AsyncSession,
        crew_id: UUID,
        input_task: str,
        tenant_id: UUID,
    ) -> CrewRun:
        """创建 Crew 执行记录."""
        data = {
            "crew_id": crew_id,
            "input_task": input_task,
            "status": "pending",
        }
        return await super().create(session, data, tenant_id)

    async def update_status(
        self,
        session: AsyncSession,
        run_id: UUID,
        status: str,
        output: str = "",
        worker_results: list[dict] | None = None,
        duration_ms: int = 0,
    ) -> CrewRun | None:
        """更新 Crew 执行状态."""
        from datetime import datetime, timezone

        data = {
            "status": status,
            "output": output,
            "worker_results": worker_results or [],
            "duration_ms": duration_ms,
        }
        if status in ("completed", "failed"):
            data["completed_at"] = datetime.now(timezone.utc)

        run = await session.get(CrewRun, run_id)
        if not run:
            return None

        for key, value in data.items():
            if hasattr(run, key):
                setattr(run, key, value)

        session.add(run)
        await session.flush()
        # NOTE: 不在这里 commit，事务边界由调用方控制
        await session.refresh(run)
        return run

    async def list_by_crew(
        self,
        session: AsyncSession,
        crew_id: UUID,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[CrewRun], int]:
        """获取 Crew 的执行历史."""
        from sqlalchemy import func

        where_clauses = [
            CrewRun.crew_id == crew_id,
            CrewRun.tenant_id == tenant_id,
        ]

        count_stmt = select(func.count()).select_from(CrewRun).where(*where_clauses)
        total_result = await session.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = (
            select(CrewRun)
            .where(*where_clauses)
            .order_by(CrewRun.started_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

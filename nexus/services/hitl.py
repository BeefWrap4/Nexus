"""HITL服务层.

提供人工审批任务的CRUD操作。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models import HITLTask
from nexus.services.base import BaseService


class HITLService(BaseService[HITLTask]):
    """人工审批任务Service."""

    def __init__(self):
        super().__init__(HITLTask)

    async def create(
        self,
        session: AsyncSession,
        data: dict[str, Any],
        tenant_id: UUID,
        user_id: UUID | None = None,
    ) -> HITLTask:
        """创建审批任务.

        Args:
            session: 数据库会话
            data: 创建数据，需包含wf_run_id, node_id, task_type, title
            tenant_id: 租户ID
            user_id: 用户ID（可选，作为assignee_id）

        Returns:
            创建的HITLTask实例
        """
        db_data = dict(data)
        db_data["tenant_id"] = tenant_id
        db_data["status"] = "pending"
        if user_id is not None and "assignee_id" not in db_data:
            db_data["assignee_id"] = user_id

        instance = HITLTask(**db_data)
        session.add(instance)
        await session.flush()
        await session.refresh(instance)
        await session.commit()
        return instance

    async def list(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 100,
        filters: dict[str, Any] | None = None,
    ) -> tuple[list[HITLTask], int]:
        """分页列表查询，支持按status、assignee_id、wf_run_id过滤."""
        return await super().list(session, tenant_id, skip, limit, filters)

    async def respond(
        self,
        session: AsyncSession,
        task_id: UUID,
        tenant_id: UUID,
        response: dict[str, Any],
        assignee_id: UUID | None = None,
    ) -> HITLTask | None:
        """响应审批任务.

        Args:
            session: 数据库会话
            task_id: 任务ID
            tenant_id: 租户ID
            response: 审批响应内容
            assignee_id: 响应人ID（可选）

        Returns:
            更新后的HITLTask实例
        """
        task = await self.get(session, task_id, tenant_id)
        if task is None:
            return None

        if task.status != "pending":
            return task  # 已处理，幂等返回

        task.response = response
        task.status = response.get("status", "approved")
        task.responded_at = datetime.now(timezone.utc)
        if assignee_id is not None:
            task.assignee_id = assignee_id

        session.add(task)
        await session.flush()
        await session.refresh(task)
        await session.commit()
        return task

    async def assign(
        self,
        session: AsyncSession,
        task_id: UUID,
        tenant_id: UUID,
        assignee_id: UUID,
    ) -> HITLTask | None:
        """分配审批任务给指定用户.

        Args:
            session: 数据库会话
            task_id: 任务ID
            tenant_id: 租户ID
            assignee_id: 被分配用户ID

        Returns:
            更新后的HITLTask实例
        """
        task = await self.get(session, task_id, tenant_id)
        if task is None:
            return None

        task.assignee_id = assignee_id
        session.add(task)
        await session.flush()
        await session.refresh(task)
        await session.commit()
        return task

    async def list_pending(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        assignee_id: UUID | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[HITLTask], int]:
        """获取待处理的审批任务.

        Args:
            session: 数据库会话
            tenant_id: 租户ID
            assignee_id: 指定被分配人（可选）
            skip: 偏移量
            limit: 每页数量

        Returns:
            (任务列表, 总数量)
        """
        filters: dict[str, Any] = {"status": "pending"}
        if assignee_id is not None:
            filters["assignee_id"] = assignee_id

        return await self.list(session, tenant_id, skip, limit, filters)

    async def list_by_run(
        self,
        session: AsyncSession,
        wf_run_id: UUID,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[HITLTask], int]:
        """获取工作流执行实例的所有审批任务.

        Args:
            session: 数据库会话
            wf_run_id: 工作流执行实例ID
            tenant_id: 租户ID
            skip: 偏移量
            limit: 每页数量

        Returns:
            (任务列表, 总数量)
        """
        filters = {"wf_run_id": wf_run_id}
        return await self.list(session, tenant_id, skip, limit, filters)

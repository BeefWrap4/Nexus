"""Workflow服务层.

提供Workflow、WorkflowVersion、WorkflowRun的CRUD操作。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models import Workflow, WorkflowVersion, WorkflowRun
from nexus.services.base import BaseService


class WorkflowService(BaseService[Workflow]):
    """工作流定义Service."""

    def __init__(self):
        super().__init__(Workflow)

    async def create(
        self,
        session: AsyncSession,
        data: dict[str, Any],
        tenant_id: UUID,
        user_id: UUID | None = None,
    ) -> Workflow:
        """创建工作流，同时创建初始版本快照."""
        workflow = await super().create(session, data, tenant_id, user_id)

        # 自动创建v1版本快照
        version = WorkflowVersion(
            workflow_id=workflow.id,
            version=1,
            config=workflow.config,
            change_notes="Initial version",
            created_by=user_id,
        )
        session.add(version)
        await session.flush()
        return workflow

    async def get_by_name(
        self,
        session: AsyncSession,
        name: str,
        tenant_id: UUID,
    ) -> Workflow | None:
        """根据名称获取工作流."""
        stmt = select(Workflow).where(
            Workflow.name == name,
            Workflow.tenant_id == tenant_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def increment_run_count(
        self,
        session: AsyncSession,
        workflow_id: UUID,
        tenant_id: UUID,
    ) -> bool:
        """增加工作流运行计数."""
        workflow = await self.get(session, workflow_id, tenant_id)
        if workflow is None:
            return False
        workflow.run_count = (workflow.run_count or 0) + 1
        session.add(workflow)
        await session.flush()
        return True


class WorkflowVersionService(BaseService[WorkflowVersion]):
    """工作流版本Service."""

    def __init__(self):
        super().__init__(WorkflowVersion)

    async def create(
        self,
        session: AsyncSession,
        data: dict[str, Any],
        tenant_id: UUID,
        user_id: UUID | None = None,
    ) -> WorkflowVersion:
        """创建新版本，自动递增版本号.

        使用 SELECT FOR UPDATE 锁定 workflow 行，防止并发下版本号冲突。
        """
        workflow_id = data.get("workflow_id")

        # 锁定 workflow 行，序列化该 workflow 的版本创建
        from sqlalchemy import func

        lock_stmt = (
            select(Workflow)
            .where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id)
            .with_for_update()
        )
        await session.execute(lock_stmt)

        # 查询当前最大版本号（在锁保护下安全）
        max_stmt = (
            select(func.coalesce(func.max(WorkflowVersion.version), 0))
            .where(WorkflowVersion.workflow_id == workflow_id)
        )
        result = await session.execute(max_stmt)
        max_version = result.scalar_one()

        db_data = dict(data)
        db_data["version"] = max_version + 1
        if user_id is not None:
            db_data["created_by"] = user_id

        version = WorkflowVersion(**db_data)
        session.add(version)
        await session.flush()
        await session.refresh(version)

        # 更新工作流的 current_version
        stmt_wf = select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.tenant_id == tenant_id,
        )
        result_wf = await session.execute(stmt_wf)
        workflow = result_wf.scalar_one_or_none()
        if workflow:
            workflow.current_version = version.version
            session.add(workflow)
            await session.flush()

        await session.commit()
        return version

    async def list_by_workflow(
        self,
        session: AsyncSession,
        workflow_id: UUID,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[WorkflowVersion], int]:
        """获取工作流的所有版本."""
        # 验证工作流归属
        stmt_wf = select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.tenant_id == tenant_id,
        )
        result_wf = await session.execute(stmt_wf)
        if result_wf.scalar_one_or_none() is None:
            return [], 0

        stmt = (
            select(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == workflow_id)
            .order_by(WorkflowVersion.version.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await session.execute(stmt)
        items = list(result.scalars().all())

        count_stmt = select(WorkflowVersion).where(
            WorkflowVersion.workflow_id == workflow_id
        )
        count_result = await session.execute(count_stmt)
        total = len(count_result.scalars().all())

        return items, total


class WorkflowRunService(BaseService[WorkflowRun]):
    """工作流执行实例Service."""

    def __init__(self):
        super().__init__(WorkflowRun)

    async def create(
        self,
        session: AsyncSession,
        data: dict[str, Any],
        tenant_id: UUID,
        user_id: UUID | None = None,
    ) -> WorkflowRun:
        """创建工作流执行实例."""
        db_data = dict(data)
        db_data["tenant_id"] = tenant_id
        db_data["status"] = db_data.get("status", "pending")

        instance = WorkflowRun(**db_data)
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
    ) -> tuple[list[WorkflowRun], int]:
        """列表查询，支持按workflow_id过滤."""
        return await super().list(session, tenant_id, skip, limit, filters)

    async def update_status(
        self,
        session: AsyncSession,
        run_id: UUID,
        tenant_id: UUID,
        status: str,
        result: dict[str, Any] | None = None,
    ) -> WorkflowRun | None:
        """更新执行状态."""
        run = await self.get(session, run_id, tenant_id)
        if run is None:
            return None

        run.status = status
        if result is not None:
            run.result = result

        session.add(run)
        await session.flush()
        await session.refresh(run)
        await session.commit()
        return run

    async def list_by_workflow(
        self,
        session: AsyncSession,
        workflow_id: UUID,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[WorkflowRun], int]:
        """获取工作流的所有执行实例."""
        filters = {"workflow_id": workflow_id}
        return await self.list(session, tenant_id, skip, limit, filters)

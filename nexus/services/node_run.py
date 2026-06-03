"""NodeRun服务层.

将 NodeRun 的 CRUD 从 RunService 中独立出来，
增加 tenant_id 参数以强化租户隔离。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models import NodeRun, WorkflowRun
from nexus.services.base import BaseService
from nexus.engine.enums import NodeStatus


class NodeRunService(BaseService[NodeRun]):
    """节点执行记录 Service."""

    def __init__(self):
        super().__init__(NodeRun)

    async def create(
        self,
        session: AsyncSession,
        wf_run_id: UUID,
        node_id: str,
        node_type: str,
        input_data: dict[str, Any] | None = None,
        tenant_id: UUID | None = None,
    ) -> NodeRun:
        """创建节点执行记录.

        Args:
            session: 数据库会话
            wf_run_id: 工作流执行实例ID
            node_id: 节点ID
            node_type: 节点类型
            input_data: 输入数据
            tenant_id: 租户ID（可选，用于验证归属）

        Returns:
            创建的NodeRun实例
        """
        # 如果提供了 tenant_id，验证 wf_run_id 的归属
        if tenant_id is not None:
            stmt = select(WorkflowRun).where(
                WorkflowRun.id == wf_run_id,
                WorkflowRun.tenant_id == tenant_id,
            )
            result = await session.execute(stmt)
            if result.scalar_one_or_none() is None:
                raise ValueError(
                    f"WorkflowRun {wf_run_id} not found for tenant {tenant_id}"
                )

        node_run = NodeRun(
            wf_run_id=wf_run_id,
            node_id=node_id,
            node_type=node_type,
            status=NodeStatus.PENDING.value,
            input_data=input_data,
        )
        session.add(node_run)
        await session.flush()
        await session.refresh(node_run)
        # NOTE: 不在这里 commit，事务边界由调用方控制
        return node_run

    async def update(
        self,
        session: AsyncSession,
        node_run_id: UUID,
        status: str,
        output_data: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> NodeRun | None:
        """更新节点执行记录.

        Args:
            session: 数据库会话
            node_run_id: 节点执行记录ID
            status: 新状态
            output_data: 输出数据（可选）
            error: 错误信息（可选）

        Returns:
            更新后的NodeRun实例
        """
        stmt = select(NodeRun).where(NodeRun.id == node_run_id)
        result = await session.execute(stmt)
        node_run = result.scalar_one_or_none()
        if node_run is None:
            return None

        node_run.status = status
        if output_data is not None:
            node_run.output_data = output_data
        if error is not None:
            node_run.error = error

        if status == NodeStatus.RUNNING and node_run.started_at is None:
            node_run.started_at = datetime.now(timezone.utc)
        if status in (NodeStatus.SUCCEEDED, NodeStatus.FAILED, NodeStatus.SKIPPED):
            node_run.completed_at = datetime.now(timezone.utc)

        session.add(node_run)
        await session.flush()
        await session.refresh(node_run)
        # NOTE: 不在这里 commit，事务边界由调用方控制
        return node_run

    async def list_by_run(
        self,
        session: AsyncSession,
        wf_run_id: UUID,
        skip: int = 0,
        limit: int = 100,
        tenant_id: UUID | None = None,
    ) -> tuple[list[NodeRun], int]:
        """获取执行实例的所有节点记录.

        Args:
            session: 数据库会话
            wf_run_id: 工作流执行实例ID
            skip: 偏移量
            limit: 每页数量
            tenant_id: 租户ID（可选，通过 join WorkflowRun 验证归属）

        Returns:
            (节点记录列表, 总数量)
        """
        stmt = (
            select(NodeRun)
            .where(NodeRun.wf_run_id == wf_run_id)
        )
        count_stmt = select(func.count()).select_from(NodeRun).where(
            NodeRun.wf_run_id == wf_run_id
        )

        if tenant_id is not None:
            stmt = stmt.join(
                WorkflowRun, NodeRun.wf_run_id == WorkflowRun.id
            ).where(WorkflowRun.tenant_id == tenant_id)
            count_stmt = count_stmt.join(
                WorkflowRun, NodeRun.wf_run_id == WorkflowRun.id
            ).where(WorkflowRun.tenant_id == tenant_id)

        stmt = stmt.order_by(NodeRun.created_at).offset(skip).limit(limit)
        result = await session.execute(stmt)
        items = list(result.scalars().all())

        count_result = await session.execute(count_stmt)
        total = count_result.scalar() or 0

        return items, total

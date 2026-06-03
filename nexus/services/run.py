"""Run服务层.

提供WorkflowRun的CRUD操作及触发执行逻辑。
"""

from __future__ import annotations

import asyncio
import traceback
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models import WorkflowRun, Workflow, NodeRun
from nexus.services.base import BaseService
from nexus.services.workflow import WorkflowService
from nexus.exceptions import (
    WorkflowNotFoundException,
    WorkflowExecutionException,
)


async def _execute_in_background(
    run_id: str,
    config: dict[str, Any],
    trigger_payload: dict[str, Any],
    runner,
):
    """后台执行工作流（ARQ 降级路径）."""
    try:
        result = await runner.execute_from_config(config, trigger_payload, run_id)
        print(f"[Runner] run_id={run_id} completed: {result.status.value}")
    except Exception:
        print(f"[Runner] run_id={run_id} failed:\n{traceback.format_exc()}")


class RunService(BaseService[WorkflowRun]):
    """工作流执行实例Service，含触发执行逻辑."""

    def __init__(self):
        super().__init__(WorkflowRun)
        self.workflow_service = WorkflowService()

    async def create(
        self,
        session: AsyncSession,
        data: dict[str, Any],
        tenant_id: UUID,
        user_id: UUID | None = None,
    ) -> WorkflowRun:
        """创建执行实例.

        Args:
            session: 数据库会话
            data: 创建数据，需包含workflow_id
            tenant_id: 租户ID
            user_id: 用户ID（可选）

        Returns:
            创建的WorkflowRun实例
        """
        workflow_id = data.get("workflow_id")
        version = 1

        if workflow_id:
            # 验证工作流存在且属于当前租户
            workflow = await self.workflow_service.get(session, workflow_id, tenant_id)
            if workflow is None:
                raise WorkflowNotFoundException(str(workflow_id))
            version = workflow.current_version or 1

        db_data = {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "workflow_id": workflow_id,
            "version": version,
            "status": "pending",
            "trigger_type": data.get("trigger_type", "manual"),
            "trigger_payload": data.get("trigger_payload", {}),
            "state": data.get("state", {}),
            "created_at": datetime.now(timezone.utc),
        }

        instance = WorkflowRun(**db_data)
        session.add(instance)
        await session.flush()
        await session.refresh(instance)
        await session.commit()
        return instance

    async def trigger(
        self,
        session: AsyncSession,
        workflow_id: UUID,
        tenant_id: UUID,
        trigger_payload: dict[str, Any] | None = None,
        trigger_type: str = "api",
    ) -> WorkflowRun:
        """触发工作流执行.

        Args:
            session: 数据库会话
            workflow_id: 工作流ID
            tenant_id: 租户ID
            trigger_payload: 触发载荷
            trigger_type: 触发类型

        Returns:
            创建的WorkflowRun实例
        """
        run_data = {
            "workflow_id": workflow_id,
            "trigger_type": trigger_type,
            "trigger_payload": trigger_payload or {},
        }
        run = await self.create(session, run_data, tenant_id)

        # Prometheus 指标：记录触发
        from nexus.observability.metrics import WORKFLOW_RUNS_TOTAL
        WORKFLOW_RUNS_TOTAL.labels(status="pending", tenant_id=str(tenant_id)).inc()

        # 增加工作流运行计数
        await self.workflow_service.increment_run_count(
            session, workflow_id, tenant_id
        )

        # 获取工作流配置用于入队
        workflow = await self.workflow_service.get(session, workflow_id, tenant_id)

        # ARQ 入队（优先）或本地降级执行
        from nexus.jobs.pool import get_arq_pool
        arq_pool = get_arq_pool()
        if arq_pool and workflow and workflow.config:
            await arq_pool.enqueue_job(
                "execute_workflow_job",
                run_id=str(run.id),
                workflow_config=workflow.config,
                trigger_payload=trigger_payload or {},
                tenant_id=str(tenant_id),
            )
        elif workflow and workflow.config:
            # 降级：本地异步执行（ARQ 未初始化时）
            from nexus.services.runner import runner as _runner
            asyncio.create_task(
                _execute_in_background(
                    run_id=str(run.id),
                    config=workflow.config,
                    trigger_payload=trigger_payload or {},
                    runner=_runner,
                )
            )

        return run

    async def get(
        self,
        session: AsyncSession,
        id: UUID,
        tenant_id: UUID,
    ) -> WorkflowRun | None:
        """根据ID获取执行实例."""
        return await super().get(session, id, tenant_id)

    async def list(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 100,
        filters: dict[str, Any] | None = None,
    ) -> tuple[list[WorkflowRun], int]:
        """分页列表查询，支持按workflow_id和status过滤."""
        return await super().list(session, tenant_id, skip, limit, filters)

    async def list_by_workflow(
        self,
        session: AsyncSession,
        workflow_id: UUID,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[WorkflowRun], int]:
        """按工作流ID查询执行记录."""
        from sqlalchemy import func, select
        from nexus.models import WorkflowRun

        stmt = (
            select(WorkflowRun)
            .where(
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.tenant_id == tenant_id,
            )
            .order_by(WorkflowRun.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await session.execute(stmt)
        items = list(result.scalars().all())

        count_stmt = select(func.count()).where(
            WorkflowRun.workflow_id == workflow_id,
            WorkflowRun.tenant_id == tenant_id,
        )
        count_result = await session.execute(count_stmt)
        total = count_result.scalar() or 0

        return items, total

    async def update(
        self,
        session: AsyncSession,
        id: UUID,
        data: dict[str, Any],
        tenant_id: UUID,
    ) -> WorkflowRun | None:
        """更新执行实例."""
        return await super().update(session, id, data, tenant_id)

    async def update_status(
        self,
        session: AsyncSession,
        run_id: UUID,
        tenant_id: UUID,
        status: str,
        result: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
    ) -> WorkflowRun | None:
        """更新执行状态.

        Args:
            session: 数据库会话
            run_id: 执行实例ID
            tenant_id: 租户ID
            status: 新状态
            result: 执行结果（可选）
            state: 当前状态（可选）

        Returns:
            更新后的WorkflowRun实例
        """
        run = await self.get(session, run_id, tenant_id)
        if run is None:
            return None

        run.status = status
        if result is not None:
            run.result = result
        if state is not None:
            run.state = state

        if status in ("completed", "failed", "cancelled"):
            run.completed_at = datetime.now(timezone.utc)
        if status == "running" and run.started_at is None:
            run.started_at = datetime.now(timezone.utc)

        session.add(run)
        await session.flush()
        await session.refresh(run)
        await session.commit()
        return run

    async def delete(
        self,
        session: AsyncSession,
        id: UUID,
        tenant_id: UUID,
    ) -> bool:
        """删除执行实例."""
        return await super().delete(session, id, tenant_id)

    async def create_node_run(
        self,
        session: AsyncSession,
        wf_run_id: UUID,
        node_id: str,
        node_type: str,
        input_data: dict[str, Any] | None = None,
    ) -> NodeRun:
        """创建节点执行记录.

        Args:
            session: 数据库会话
            wf_run_id: 工作流执行实例ID
            node_id: 节点ID
            node_type: 节点类型
            input_data: 输入数据

        Returns:
            创建的NodeRun实例
        """
        node_run = NodeRun(
            wf_run_id=wf_run_id,
            node_id=node_id,
            node_type=node_type,
            status="pending",
            input_data=input_data,
        )
        session.add(node_run)
        await session.flush()
        await session.refresh(node_run)
        await session.commit()
        return node_run

    async def update_node_run(
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

        if status == "running" and node_run.started_at is None:
            node_run.started_at = datetime.now(timezone.utc)
        if status in ("succeeded", "failed", "skipped"):
            node_run.completed_at = datetime.now(timezone.utc)

        session.add(node_run)
        await session.flush()
        await session.refresh(node_run)
        await session.commit()
        return node_run

    async def list_node_runs(
        self,
        session: AsyncSession,
        wf_run_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[NodeRun], int]:
        """获取执行实例的所有节点记录.

        Args:
            session: 数据库会话
            wf_run_id: 工作流执行实例ID
            skip: 偏移量
            limit: 每页数量

        Returns:
            (节点记录列表, 总数量)
        """
        from sqlalchemy import func

        stmt = (
            select(NodeRun)
            .where(NodeRun.wf_run_id == wf_run_id)
            .order_by(NodeRun.created_at)
            .offset(skip)
            .limit(limit)
        )
        result = await session.execute(stmt)
        items = list(result.scalars().all())

        count_stmt = select(func.count()).where(NodeRun.wf_run_id == wf_run_id)
        count_result = await session.execute(count_stmt)
        total = count_result.scalar() or 0

        return items, total

    async def list_artifacts_by_run(
        self,
        session: AsyncSession,
        run_id: UUID,
        tenant_id: UUID,
    ) -> list[dict[str, Any]]:
        """获取执行实例的所有输出产物.

        Args:
            session: 数据库会话
            run_id: 执行实例ID
            tenant_id: 租户ID

        Returns:
            产物列表（已序列化为 dict）
        """
        from sqlalchemy import select
        from nexus.models.audit import Artifact

        stmt = (
            select(Artifact)
            .where(Artifact.wf_run_id == run_id, Artifact.tenant_id == tenant_id)
            .order_by(Artifact.created_at)
        )
        result = await session.execute(stmt)
        artifacts = result.scalars().all()
        return [
            {
                "id": str(a.id),
                "name": a.name,
                "type": a.type,
                "mime_type": a.mime_type,
                "size_bytes": a.size_bytes,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in artifacts
        ]

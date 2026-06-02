"""Service层单元测试.

覆盖:
- BaseService CRUD操作
- WorkflowService（创建、版本快照、按名查询）
- WorkflowVersionService（自动递增版本号）
- WorkflowRunService（状态更新、按工作流过滤）
- RunService（触发执行、节点记录）
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models import Workflow, WorkflowRun, WorkflowVersion, NodeRun
from nexus.services.base import BaseService
from nexus.services.workflow import WorkflowService, WorkflowVersionService
from nexus.services.run import RunService
from nexus.exceptions import WorkflowExecutionException, WorkflowNotFoundException


# ---------------------------------------------------------------------------
# BaseService Tests
# ---------------------------------------------------------------------------

class TestBaseService:
    """测试Service基类."""

    @pytest.mark.asyncio
    async def test_create(self, db_session: AsyncSession):
        """测试创建记录."""
        service = BaseService(Workflow)
        tenant_id = uuid4()
        user_id = uuid4()

        wf = await service.create(
            db_session,
            data={
                "name": "Test Workflow",
                "config": {"nodes": [], "edges": []},
            },
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        assert wf.id is not None
        assert wf.tenant_id == tenant_id
        assert wf.created_by == user_id
        assert wf.name == "Test Workflow"

    @pytest.mark.asyncio
    async def test_get(self, db_session: AsyncSession):
        """测试根据ID获取记录."""
        service = BaseService(Workflow)
        tenant_id = uuid4()
        user_id = uuid4()

        created = await service.create(
            db_session,
            data={
                "name": "Get Test",
                "config": {},
            },
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        fetched = await service.get(db_session, created.id, tenant_id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == "Get Test"

    @pytest.mark.asyncio
    async def test_get_wrong_tenant(self, db_session: AsyncSession):
        """测试跨租户获取应返回None."""
        service = BaseService(Workflow)
        tenant_id = uuid4()
        wrong_tenant = uuid4()
        user_id = uuid4()

        created = await service.create(
            db_session,
            data={"name": "Tenant Test", "config": {}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        fetched = await service.get(db_session, created.id, wrong_tenant)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_list_pagination(self, db_session: AsyncSession):
        """测试分页列表查询."""
        service = BaseService(Workflow)
        tenant_id = uuid4()
        user_id = uuid4()

        for i in range(5):
            await service.create(
                db_session,
                data={"name": f"Workflow {i}", "config": {}},
                tenant_id=tenant_id,
                user_id=user_id,
            )
        await db_session.commit()

        items, total = await service.list(db_session, tenant_id, skip=0, limit=3)
        assert len(items) == 3
        assert total == 5

    @pytest.mark.asyncio
    async def test_list_with_filters(self, db_session: AsyncSession):
        """测试带过滤条件的列表查询."""
        service = BaseService(Workflow)
        tenant_id = uuid4()
        user_id = uuid4()

        await service.create(
            db_session,
            data={"name": "Active WF", "config": {}, "status": "active"},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await service.create(
            db_session,
            data={"name": "Draft WF", "config": {}, "status": "draft"},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        items, total = await service.list(
            db_session, tenant_id, filters={"status": "active"}
        )
        assert total == 1
        assert items[0].name == "Active WF"

    @pytest.mark.asyncio
    async def test_update(self, db_session: AsyncSession):
        """测试更新记录."""
        service = BaseService(Workflow)
        tenant_id = uuid4()
        user_id = uuid4()

        created = await service.create(
            db_session,
            data={"name": "Old Name", "config": {}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        updated = await service.update(
            db_session, created.id, {"name": "New Name"}, tenant_id
        )
        await db_session.commit()

        assert updated is not None
        assert updated.name == "New Name"

    @pytest.mark.asyncio
    async def test_update_none_values_ignored(self, db_session: AsyncSession):
        """测试None值不应覆盖现有字段."""
        service = BaseService(Workflow)
        tenant_id = uuid4()
        user_id = uuid4()

        created = await service.create(
            db_session,
            data={"name": "Original", "description": "Desc", "config": {}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        updated = await service.update(
            db_session, created.id, {"name": None, "description": "New Desc"}, tenant_id
        )
        await db_session.commit()

        assert updated.name == "Original"
        assert updated.description == "New Desc"

    @pytest.mark.asyncio
    async def test_delete(self, db_session: AsyncSession):
        """测试删除记录."""
        service = BaseService(Workflow)
        tenant_id = uuid4()
        user_id = uuid4()

        created = await service.create(
            db_session,
            data={"name": "To Delete", "config": {}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        ok = await service.delete(db_session, created.id, tenant_id)
        await db_session.commit()

        assert ok is True
        fetched = await service.get(db_session, created.id, tenant_id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_delete_not_found(self, db_session: AsyncSession):
        """测试删除不存在的记录应返回False."""
        service = BaseService(Workflow)
        tenant_id = uuid4()

        ok = await service.delete(db_session, uuid4(), tenant_id)
        assert ok is False


# ---------------------------------------------------------------------------
# WorkflowService Tests
# ---------------------------------------------------------------------------

class TestWorkflowService:
    """测试WorkflowService."""

    @pytest.mark.asyncio
    async def test_create_creates_initial_version(self, db_session: AsyncSession):
        """创建工作流时应自动创建v1版本快照."""
        from sqlalchemy import select
        from nexus.models import WorkflowVersion

        service = WorkflowService()
        tenant_id = uuid4()
        user_id = uuid4()

        wf = await service.create(
            db_session,
            data={
                "name": "Auto Version WF",
                "config": {"nodes": [], "edges": []},
            },
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        # 重新查询以获取最新状态（避免 async lazy load 问题）
        stmt = select(WorkflowVersion).where(WorkflowVersion.workflow_id == wf.id)
        result = await db_session.execute(stmt)
        versions = result.scalars().all()

        assert wf.current_version == 1
        # 验证版本已创建
        assert len(versions) == 1
        assert versions[0].version == 1
        assert versions[0].change_notes == "Initial version"

    @pytest.mark.asyncio
    async def test_get_by_name(self, db_session: AsyncSession):
        """测试按名称查询工作流."""
        service = WorkflowService()
        tenant_id = uuid4()
        user_id = uuid4()

        await service.create(
            db_session,
            data={"name": "Unique Name", "config": {}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        found = await service.get_by_name(db_session, "Unique Name", tenant_id)
        assert found is not None
        assert found.name == "Unique Name"

        not_found = await service.get_by_name(db_session, "No Such Name", tenant_id)
        assert not_found is None

    @pytest.mark.asyncio
    async def test_get_by_name_wrong_tenant(self, db_session: AsyncSession):
        """测试跨租户按名称查询应返回None."""
        service = WorkflowService()
        tenant_id = uuid4()
        other_tenant = uuid4()
        user_id = uuid4()

        await service.create(
            db_session,
            data={"name": "Tenant Bound", "config": {}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        found = await service.get_by_name(db_session, "Tenant Bound", other_tenant)
        assert found is None

    @pytest.mark.asyncio
    async def test_increment_run_count(self, db_session: AsyncSession):
        """测试增加运行计数."""
        service = WorkflowService()
        tenant_id = uuid4()
        user_id = uuid4()

        wf = await service.create(
            db_session,
            data={"name": "Counter WF", "config": {}, "run_count": 0},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        ok = await service.increment_run_count(db_session, wf.id, tenant_id)
        await db_session.commit()

        assert ok is True
        updated = await service.get(db_session, wf.id, tenant_id)
        assert updated.run_count == 1

    @pytest.mark.asyncio
    async def test_increment_run_count_not_found(self, db_session: AsyncSession):
        """测试对不存在的工作流增加计数应返回False."""
        service = WorkflowService()
        tenant_id = uuid4()

        ok = await service.increment_run_count(db_session, uuid4(), tenant_id)
        assert ok is False


# ---------------------------------------------------------------------------
# WorkflowVersionService Tests
# ---------------------------------------------------------------------------

class TestWorkflowVersionService:
    """测试WorkflowVersionService."""

    @pytest.mark.asyncio
    async def test_create_auto_increments_version(self, db_session: AsyncSession):
        """创建版本时应自动递增版本号."""
        wf_service = WorkflowService()
        ver_service = WorkflowVersionService()
        tenant_id = uuid4()
        user_id = uuid4()

        wf = await wf_service.create(
            db_session,
            data={"name": "Versioned WF", "config": {"v": 1}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        # 创建v2
        v2 = await ver_service.create(
            db_session,
            data={"workflow_id": wf.id, "config": {"v": 2}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        assert v2.version == 2

        # 创建v3
        v3 = await ver_service.create(
            db_session,
            data={"workflow_id": wf.id, "config": {"v": 3}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        assert v3.version == 3

    @pytest.mark.asyncio
    async def test_create_updates_workflow_current_version(
        self, db_session: AsyncSession
    ):
        """创建新版本时应更新工作流的current_version."""
        wf_service = WorkflowService()
        ver_service = WorkflowVersionService()
        tenant_id = uuid4()
        user_id = uuid4()

        wf = await wf_service.create(
            db_session,
            data={"name": "Auto Current Version", "config": {}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()
        assert wf.current_version == 1

        await ver_service.create(
            db_session,
            data={"workflow_id": wf.id, "config": {}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        updated_wf = await wf_service.get(db_session, wf.id, tenant_id)
        assert updated_wf.current_version == 2

    @pytest.mark.asyncio
    async def test_list_by_workflow(self, db_session: AsyncSession):
        """测试获取工作流的所有版本."""
        wf_service = WorkflowService()
        ver_service = WorkflowVersionService()
        tenant_id = uuid4()
        user_id = uuid4()

        wf = await wf_service.create(
            db_session,
            data={"name": "List Versions", "config": {}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        items, total = await ver_service.list_by_workflow(
            db_session, wf.id, tenant_id
        )
        # 初始创建时已有一个版本
        assert total >= 1

    @pytest.mark.asyncio
    async def test_list_by_workflow_wrong_tenant(self, db_session: AsyncSession):
        """测试跨租户列出版本应返回空."""
        wf_service = WorkflowService()
        ver_service = WorkflowVersionService()
        tenant_id = uuid4()
        wrong_tenant = uuid4()
        user_id = uuid4()

        wf = await wf_service.create(
            db_session,
            data={"name": "Tenant Version", "config": {}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        items, total = await ver_service.list_by_workflow(
            db_session, wf.id, wrong_tenant
        )
        assert total == 0
        assert items == []


# ---------------------------------------------------------------------------
# RunService Tests
# ---------------------------------------------------------------------------

class TestRunService:
    """测试RunService."""

    @pytest.mark.asyncio
    async def test_create_requires_workflow_id(self, db_session: AsyncSession):
        """创建Run时必须提供workflow_id."""
        service = RunService()
        tenant_id = uuid4()

        with pytest.raises(WorkflowExecutionException) as exc_info:
            await service.create(
                db_session,
                data={"trigger_type": "manual"},
                tenant_id=tenant_id,
            )
        assert "workflow_id is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_validates_workflow_exists(self, db_session: AsyncSession):
        """创建Run时应验证工作流存在."""
        service = RunService()
        tenant_id = uuid4()

        with pytest.raises(WorkflowNotFoundException):
            await service.create(
                db_session,
                data={"workflow_id": uuid4(), "trigger_type": "manual"},
                tenant_id=tenant_id,
            )

    @pytest.mark.asyncio
    async def test_trigger_creates_run_and_increments_count(
        self, db_session: AsyncSession
    ):
        """触发执行应创建Run并增加工作流计数."""
        wf_service = WorkflowService()
        run_service = RunService()
        tenant_id = uuid4()
        user_id = uuid4()

        wf = await wf_service.create(
            db_session,
            data={"name": "Trigger Test", "config": {}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        run = await run_service.trigger(
            db_session,
            workflow_id=wf.id,
            tenant_id=tenant_id,
            trigger_payload={"key": "value"},
            trigger_type="api",
        )
        await db_session.commit()

        assert run.workflow_id == wf.id
        assert run.status == "pending"
        assert run.trigger_type == "api"
        assert run.trigger_payload == {"key": "value"}

        # 验证计数增加
        updated_wf = await wf_service.get(db_session, wf.id, tenant_id)
        assert updated_wf.run_count == 1

    @pytest.mark.asyncio
    async def test_update_status(self, db_session: AsyncSession):
        """测试更新执行状态."""
        wf_service = WorkflowService()
        run_service = RunService()
        tenant_id = uuid4()
        user_id = uuid4()

        wf = await wf_service.create(
            db_session,
            data={"name": "Status Test", "config": {}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        run = await run_service.trigger(
            db_session, wf.id, tenant_id, trigger_type="manual"
        )
        await db_session.commit()

        updated = await run_service.update_status(
            db_session, run.id, tenant_id, "running"
        )
        await db_session.commit()

        assert updated.status == "running"
        assert updated.started_at is not None

    @pytest.mark.asyncio
    async def test_update_status_to_completed(self, db_session: AsyncSession):
        """测试完成状态应设置completed_at."""
        wf_service = WorkflowService()
        run_service = RunService()
        tenant_id = uuid4()
        user_id = uuid4()

        wf = await wf_service.create(
            db_session,
            data={"name": "Complete Test", "config": {}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        run = await run_service.trigger(
            db_session, wf.id, tenant_id, trigger_type="manual"
        )
        await db_session.commit()

        updated = await run_service.update_status(
            db_session, run.id, tenant_id, "completed", result={"output": "done"}
        )
        await db_session.commit()

        assert updated.status == "completed"
        assert updated.result == {"output": "done"}
        assert updated.completed_at is not None

    @pytest.mark.asyncio
    async def test_list_by_workflow(self, db_session: AsyncSession):
        """测试按工作流列出执行记录."""
        wf_service = WorkflowService()
        run_service = RunService()
        tenant_id = uuid4()
        user_id = uuid4()

        wf = await wf_service.create(
            db_session,
            data={"name": "List Runs", "config": {}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        for i in range(3):
            await run_service.trigger(
                db_session, wf.id, tenant_id, trigger_type="manual"
            )
        await db_session.commit()

        items, total = await run_service.list_by_workflow(
            db_session, wf.id, tenant_id
        )
        assert total == 3
        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_create_node_run(self, db_session: AsyncSession):
        """测试创建节点执行记录."""
        wf_service = WorkflowService()
        run_service = RunService()
        tenant_id = uuid4()
        user_id = uuid4()

        wf = await wf_service.create(
            db_session,
            data={"name": "Node Run Test", "config": {}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        run = await run_service.trigger(
            db_session, wf.id, tenant_id, trigger_type="manual"
        )
        await db_session.commit()

        node_run = await run_service.create_node_run(
            db_session,
            wf_run_id=run.id,
            node_id="agent_1",
            node_type="agent",
            input_data={"prompt": "hello"},
        )
        await db_session.commit()

        assert node_run.wf_run_id == run.id
        assert node_run.node_id == "agent_1"
        assert node_run.node_type == "agent"
        assert node_run.status == "pending"
        assert node_run.input_data == {"prompt": "hello"}

    @pytest.mark.asyncio
    async def test_update_node_run(self, db_session: AsyncSession):
        """测试更新节点执行记录."""
        wf_service = WorkflowService()
        run_service = RunService()
        tenant_id = uuid4()
        user_id = uuid4()

        wf = await wf_service.create(
            db_session,
            data={"name": "Update Node Run", "config": {}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        run = await run_service.trigger(
            db_session, wf.id, tenant_id, trigger_type="manual"
        )
        await db_session.commit()

        node_run = await run_service.create_node_run(
            db_session, run.id, "agent_1", "agent"
        )
        await db_session.commit()

        updated = await run_service.update_node_run(
            db_session,
            node_run_id=node_run.id,
            status="succeeded",
            output_data={"result": "ok"},
        )
        await db_session.commit()

        assert updated.status == "succeeded"
        assert updated.output_data == {"result": "ok"}
        assert updated.completed_at is not None

    @pytest.mark.asyncio
    async def test_list_node_runs(self, db_session: AsyncSession):
        """测试列出执行实例的所有节点记录."""
        wf_service = WorkflowService()
        run_service = RunService()
        tenant_id = uuid4()
        user_id = uuid4()

        wf = await wf_service.create(
            db_session,
            data={"name": "List Node Runs", "config": {}},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db_session.commit()

        run = await run_service.trigger(
            db_session, wf.id, tenant_id, trigger_type="manual"
        )
        await db_session.commit()

        for i in range(3):
            await run_service.create_node_run(
                db_session, run.id, f"node_{i}", "agent"
            )
        await db_session.commit()

        items, total = await run_service.list_node_runs(db_session, run.id)
        assert total == 3
        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_update_node_run_not_found(self, db_session: AsyncSession):
        """测试更新不存在的节点记录应返回None."""
        run_service = RunService()

        result = await run_service.update_node_run(
            db_session, uuid4(), "succeeded"
        )
        assert result is None

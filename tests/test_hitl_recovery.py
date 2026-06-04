"""HITL 状态恢复测试.

覆盖:
- Worker 启动时扫描 pending 状态的 HITL 任务
- HITL 超时状态转换
- 恢复后 EventBus 重新订阅
- HITL 状态机完整转换链
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.engine.enums import HITLStatus
from nexus.engine.hitl_controller import (
    HITLController,
    HITLResponse,
    HITLTask,
    HITLType,
)
from nexus.exceptions import HITLTimeoutException


class TestHITLRecovery:
    """HITL 状态恢复测试."""

    @pytest.fixture
    def mock_event_bus(self):
        """创建 mock EventBus."""
        bus = MagicMock()
        bus.publish = AsyncMock()
        bus.subscribe = MagicMock(return_value="sub_id_123")
        bus.unsubscribe = MagicMock()
        return bus

    @pytest.fixture
    def controller(self, mock_event_bus):
        """创建 HITLController 实例."""
        return HITLController(event_bus=mock_event_bus)

    @pytest.mark.asyncio
    async def test_worker_startup_scans_pending_tasks(self):
        """验证 recover_hitl_tasks 扫描 pending 状态的 HITL 任务.

        recover_hitl_tasks 内部通过局部导入使用 nexus.db.database.AsyncSessionLocal,
        因此 mock 目标应为 nexus.db.database.AsyncSessionLocal。
        """
        from nexus.jobs.config import recover_hitl_tasks

        # 构造 mock ORM 记录
        mock_task = MagicMock()
        mock_task.id = "task-001"
        mock_task.wf_run_id = "run-001"
        mock_task.node_id = "node-1"
        mock_task.task_type = "approve"
        mock_task.title = "Test approval"
        mock_task.description = "Test description"
        mock_task.context = {"key": "value"}
        mock_task.assignee_id = "user-1"
        mock_task.status = "pending"
        mock_task.deadline = datetime.now(timezone.utc) + timedelta(hours=1)
        mock_task.responded_at = None
        mock_task.created_at = datetime.now(timezone.utc)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[mock_task]))
        )
        mock_session.execute.return_value = mock_result

        # Mock 目标必须匹配局部导入路径: from nexus.db.database import AsyncSessionLocal
        with patch("nexus.db.database.AsyncSessionLocal", return_value=mock_session):
            recovered = await recover_hitl_tasks()

        assert len(recovered) == 1
        assert recovered[0]["id"] == "task-001"
        assert recovered[0]["wf_run_id"] == "run-001"
        assert recovered[0]["status"] == "pending"
        assert recovered[0]["task_type"] == "approve"

    @pytest.mark.asyncio
    async def test_worker_startup_no_pending_tasks(self):
        """验证无 pending 任务时返回空列表."""
        from nexus.jobs.config import recover_hitl_tasks

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[]))
        )
        mock_session.execute.return_value = mock_result

        with patch("nexus.db.database.AsyncSessionLocal", return_value=mock_session):
            recovered = await recover_hitl_tasks()

        assert recovered == []

    @pytest.mark.asyncio
    async def test_hitl_timeout_transitions_to_timeout(self, controller):
        """HITL 任务超时后内存状态变为 timeout.

        直接注入内存任务 + mock _load_hitl_task_from_db，
        绕过 DB 持久化，验证 timeout 状态转换。
        """
        task = HITLTask(
            id="timeout-task-1",
            run_id="run-1",
            node_id="node-1",
            task_type=HITLType.APPROVE,
            title="Test timeout",
            description="Testing timeout behavior",
            context={},
            deadline=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        async with controller._lock:
            controller._tasks[task.id] = task

        # Mock _load_hitl_task_from_db 返回一个有 task 但没有 response 的记录，
        # 避免 HITLTaskNotFoundException 中断流程。
        mock_db_task = MagicMock()
        mock_db_task.response = None
        mock_db_task.status = "pending"
        controller._load_hitl_task_from_db = AsyncMock(return_value=mock_db_task)

        # 极小超时确保立即触发 TimeoutError
        with pytest.raises(HITLTimeoutException):
            await controller.wait_for_response(task.id, timeout=0.001)

        retrieved = controller._tasks.get(task.id)
        assert retrieved is not None
        assert retrieved.status == HITLStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_recover_subscribes_eventbus(self, controller):
        """等待响应时 EventBus.subscribe 被调用.

        直接注入内存任务 + mock DB，调用 wait_for_response 验证 subscribe。
        """
        task = HITLTask(
            id="sub-task-1",
            run_id="run-1",
            node_id="node-1",
            task_type=HITLType.APPROVE,
            title="Test subscription",
            description="Verify EventBus subscription",
            context={},
        )
        async with controller._lock:
            controller._tasks[task.id] = task

        # Mock DB 检查：返回无 response 的记录，让流程继续到 EventBus 订阅
        mock_db_task = MagicMock()
        mock_db_task.response = None
        mock_db_task.status = "pending"
        controller._load_hitl_task_from_db = AsyncMock(return_value=mock_db_task)

        # 后台启动等待
        async def _wait():
            try:
                await controller.wait_for_response(task.id, timeout=0.01)
            except HITLTimeoutException:
                pass
            except Exception:
                pass

        wait_task = asyncio.create_task(_wait())
        await asyncio.sleep(0.05)

        # 验证 subscribe 被调用
        controller.event_bus.subscribe.assert_called()
        call_args = controller.event_bus.subscribe.call_args
        assert call_args is not None
        channel = call_args[0][0]
        assert task.id in channel

        # 清理
        wait_task.cancel()
        try:
            await wait_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_recover_hitl_tasks_handles_db_error(self):
        """验证 recover_hitl_tasks 在数据库异常时向上传播."""
        from nexus.jobs.config import recover_hitl_tasks

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.execute = AsyncMock(side_effect=Exception("DB connection failed"))

        with patch("nexus.db.database.AsyncSessionLocal", return_value=mock_session):
            with pytest.raises(Exception, match="DB connection failed"):
                await recover_hitl_tasks()


class TestHITLStatusTransitions:
    """HITL 状态机测试.

    使用 controller.create_task 创建任务；DB 持久化失败时自动降级到纯内存模式。
    """

    @pytest.fixture
    def mock_event_bus(self):
        """创建 mock EventBus."""
        bus = MagicMock()
        bus.publish = AsyncMock()
        bus.subscribe = MagicMock(return_value="sub_id")
        bus.unsubscribe = MagicMock()
        return bus

    @pytest.fixture
    def controller(self, mock_event_bus):
        """创建 HITLController 实例."""
        return HITLController(event_bus=mock_event_bus)

    @pytest.mark.asyncio
    async def test_pending_to_approved(self, controller):
        """pending -> approved 转换."""
        task = await controller.create_task(
            run_id="run-1",
            node_id="node-1",
            task_type=HITLType.APPROVE,
            title="Approve test",
            description="Test approval",
            context={},
        )
        assert task.status == HITLStatus.PENDING

        response = HITLResponse(approved=True, notes="Looks good")
        result = await controller.submit_response(task.id, "user-1", response)
        assert result.status == HITLStatus.APPROVED
        assert result.response.approved is True

    @pytest.mark.asyncio
    async def test_pending_to_rejected(self, controller):
        """pending -> rejected 转换."""
        task = await controller.create_task(
            run_id="run-1",
            node_id="node-1",
            task_type=HITLType.APPROVE,
            title="Reject test",
            description="Test rejection",
            context={},
        )
        assert task.status == HITLStatus.PENDING

        response = HITLResponse(approved=False, notes="Needs changes")
        result = await controller.submit_response(task.id, "user-1", response)
        assert result.status == HITLStatus.REJECTED
        assert result.response.approved is False

    @pytest.mark.asyncio
    async def test_pending_to_timeout(self, controller):
        """pending -> timeout 转换（通过超时触发）.

        直接注入内存任务 + mock DB，避免 DB 缺失导致 HITLTaskNotFoundException。
        """
        task = HITLTask(
            id="timeout-transition-1",
            run_id="run-1",
            node_id="node-1",
            task_type=HITLType.APPROVE,
            title="Timeout transition test",
            description="Test timeout",
            context={},
        )
        async with controller._lock:
            controller._tasks[task.id] = task

        # Mock DB: 返回无 response 的记录
        mock_db_task = MagicMock()
        mock_db_task.response = None
        mock_db_task.status = "pending"
        controller._load_hitl_task_from_db = AsyncMock(return_value=mock_db_task)

        with pytest.raises(HITLTimeoutException):
            await controller.wait_for_response(task.id, timeout=0.001)

        retrieved = controller._tasks.get(task.id)
        assert retrieved.status == HITLStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_already_responded_rejects_second_response(self, controller):
        """已响应的任务拒绝第二次响应."""
        from nexus.exceptions import HITLException

        task = await controller.create_task(
            run_id="run-1",
            node_id="node-1",
            task_type=HITLType.APPROVE,
            title="Double response test",
            description="Test double response prevention",
            context={},
        )

        # 第一次响应
        response = HITLResponse(approved=True)
        await controller.submit_response(task.id, "user-1", response)

        # 第二次响应应抛出异常
        with pytest.raises(HITLException, match="already"):
            response2 = HITLResponse(approved=False)
            await controller.submit_response(task.id, "user-1", response2)

    @pytest.mark.asyncio
    async def test_cancel_transitions_to_rejected(self, controller):
        """取消任务状态变为 rejected."""
        task = await controller.create_task(
            run_id="run-1",
            node_id="node-1",
            task_type=HITLType.APPROVE,
            title="Cancel test",
            description="Test cancellation",
            context={},
        )

        result = await controller.cancel_task(task.id, "user-1")
        assert result.status == HITLStatus.REJECTED
        assert result.response.approved is False
        assert "Cancelled" in result.response.notes

    def test_hitl_status_enum_values(self):
        """验证 HITLStatus 枚举值."""
        assert HITLStatus.PENDING.value == "pending"
        assert HITLStatus.APPROVED.value == "approved"
        assert HITLStatus.REJECTED.value == "rejected"
        assert HITLStatus.TIMEOUT.value == "timeout"

    def test_hitl_type_enum_values(self):
        """验证 HITLType 枚举值."""
        assert HITLType.APPROVE.value == "approve"
        assert HITLType.SELECT.value == "select"
        assert HITLType.INPUT.value == "input"
        assert HITLType.CORRECT.value == "correct"

    def test_hitl_response_default_values(self):
        """验证 HITLResponse 默认值."""
        resp = HITLResponse()
        assert resp.approved is True
        assert resp.selection is None
        assert resp.input_data is None
        assert resp.correction is None
        assert resp.notes is None

    def test_default_timeout_response_approve(self, controller):
        """APPROVE 类型超时默认拒绝."""
        loop = asyncio.new_event_loop()
        resp = loop.run_until_complete(
            controller.get_default_timeout_response(HITLType.APPROVE)
        )
        loop.close()
        assert resp.approved is False
        assert "Auto-rejected" in resp.notes

    def test_default_timeout_response_select(self, controller):
        """SELECT 类型超时默认通过但无选择."""
        loop = asyncio.new_event_loop()
        resp = loop.run_until_complete(
            controller.get_default_timeout_response(HITLType.SELECT)
        )
        loop.close()
        assert resp.approved is True
        assert resp.selection is None

    def test_default_timeout_response_input(self, controller):
        """INPUT 类型超时默认空输入."""
        loop = asyncio.new_event_loop()
        resp = loop.run_until_complete(
            controller.get_default_timeout_response(HITLType.INPUT)
        )
        loop.close()
        assert resp.approved is True
        assert resp.input_data == {}

    def test_default_timeout_response_correct(self, controller):
        """CORRECT 类型超时默认空修正."""
        loop = asyncio.new_event_loop()
        resp = loop.run_until_complete(
            controller.get_default_timeout_response(HITLType.CORRECT)
        )
        loop.close()
        assert resp.approved is True
        assert resp.correction == {}

    @pytest.mark.asyncio
    async def test_get_pending_tasks_filters_by_assignee(self, controller):
        """get_pending_tasks 按 assignee_id 过滤."""
        task1 = await controller.create_task(
            run_id="run-1",
            node_id="node-1",
            task_type=HITLType.APPROVE,
            title="Task for user1",
            description="Test",
            context={},
            assignee_id="user-1",
        )
        task2 = await controller.create_task(
            run_id="run-2",
            node_id="node-2",
            task_type=HITLType.APPROVE,
            title="Task for user2",
            description="Test",
            context={},
            assignee_id="user-2",
        )

        # 按 assignee 过滤
        user1_tasks = await controller.get_pending_tasks(assignee_id="user-1")
        assert len(user1_tasks) == 1
        assert user1_tasks[0].id == task1.id

        # 不过滤应返回所有 pending
        all_tasks = await controller.get_pending_tasks()
        assert len(all_tasks) == 2

    def test_hitl_task_post_init_sets_defaults(self):
        """HITLTask __post_init__ 设置默认值."""
        task = HITLTask(
            id="test-id",
            run_id="run-1",
            node_id="node-1",
            task_type=HITLType.APPROVE,
            title="Test",
            description="Test desc",
            context={},
        )
        assert task.created_at is not None
        assert task.deadline is not None
        assert task.status == HITLStatus.PENDING
        assert task.response is None
        assert task.responded_at is None

    @pytest.mark.asyncio
    async def test_submit_response_with_wrong_assignee(self, controller):
        """非指定 assignee 提交响应应被拒绝."""
        from nexus.exceptions import PermissionDeniedException

        task = await controller.create_task(
            run_id="run-1",
            node_id="node-1",
            task_type=HITLType.APPROVE,
            title="Assignee test",
            description="Test assignee restriction",
            context={},
            assignee_id="user-1",
        )

        response = HITLResponse(approved=True)
        with pytest.raises(PermissionDeniedException):
            await controller.submit_response(task.id, "user-2", response)

    @pytest.mark.asyncio
    async def test_get_task_returns_from_memory(self, controller):
        """get_task 从内存返回任务."""
        task = await controller.create_task(
            run_id="run-1",
            node_id="node-1",
            task_type=HITLType.APPROVE,
            title="Memory test",
            description="Test memory retrieval",
            context={},
        )

        retrieved = await controller.get_task(task.id)
        assert retrieved is not None
        assert retrieved.id == task.id
        assert retrieved.title == "Memory test"

    @pytest.mark.asyncio
    async def test_get_task_not_found(self, controller):
        """get_task 对不存在的任务抛出异常."""
        from nexus.exceptions import HITLTaskNotFoundException

        with pytest.raises(HITLTaskNotFoundException):
            await controller.get_task("nonexistent-id")

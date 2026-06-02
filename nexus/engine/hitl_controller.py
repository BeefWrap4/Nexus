"""人工在环控制器.

基于WAT HumanProxy 升级:
- 从被动等待升级为主动审批流
- 4种审批类型: approve/select/input/correct
- 超时机制 + 默认策略
- 多渠道通知

借鉴LangGraph interrupt() + Camunda Human Task。
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from nexus.config import settings
from nexus.engine.event_bus import EventBus
from nexus.exceptions import HITLException, HITLTaskNotFoundException, HITLTimeoutException


class HITLType(str, Enum):
    """审批类型."""

    APPROVE = "approve"  # 通过/拒绝二选一
    SELECT = "select"  # 多选一
    INPUT = "input"  # 补充信息
    CORRECT = "correct"  # 纠错修正


class HITLStatus(str, Enum):
    """审批状态."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


@dataclass
class HITLResponse:
    """审批响应."""

    approved: bool = True
    selection: Optional[str] = None
    input_data: Optional[dict[str, Any]] = None
    correction: Optional[dict[str, Any]] = None
    notes: Optional[str] = None


@dataclass
class HITLTask:
    """审批任务."""

    id: str
    run_id: str
    node_id: str
    task_type: HITLType
    title: str
    description: str
    context: dict[str, Any]
    assignee_id: Optional[str] = None
    status: HITLStatus = HITLStatus.PENDING
    response: Optional[HITLResponse] = None
    deadline: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.deadline is None:
            self.deadline = datetime.now(timezone.utc) + timedelta(
                seconds=settings.DEFAULT_HITL_TIMEOUT_SECONDS
            )


class HITLController:
    """人工在环控制器."""

    def __init__(
        self,
        event_bus: EventBus,
        notification_service=None,
    ):
        self.event_bus = event_bus
        self.notification = notification_service
        self._tasks: dict[str, HITLTask] = {}  # 内存缓存
        self._waiters: dict[str, asyncio.Future] = {}  # 等待响应的Future
        self._lock = asyncio.Lock()  # 并发安全锁

    async def create_task(
        self,
        run_id: str,
        node_id: str,
        task_type: HITLType,
        title: str,
        description: str,
        context: dict[str, Any],
        assignee_id: Optional[str] = None,
        deadline: Optional[datetime] = None,
    ) -> HITLTask:
        """创建审批任务 - 工作流在此处暂停.

        对应WAT HumanProxy等待前端输入。
        """
        import uuid

        task = HITLTask(
            id=str(uuid.uuid4()),
            run_id=run_id,
            node_id=node_id,
            task_type=task_type,
            title=title,
            description=description,
            context=context,
            assignee_id=assignee_id,
            deadline=deadline,
        )

        async with self._lock:
            self._tasks[task.id] = task

        # 2. 推送WebSocket事件（实时通知前端）
        await self.event_bus.publish(
            {
                "type": "hitl_request",
                "run_id": run_id,
                "node_id": node_id,
                "task_id": task.id,
                "task_type": task_type.value,
                "title": title,
                "description": description,
                "context": context,
                "deadline": task.deadline.isoformat() if task.deadline else None,
            }
        )

        # 3. 多渠道通知
        if self.notification and assignee_id:
            await self.notification.send(
                user_id=assignee_id,
                channels=settings.HITL_NOTIFICATION_CHANNELS,
                payload={
                    "type": "hitl_request",
                    "task_id": task.id,
                    "title": title,
                    "run_id": run_id,
                },
            )

        return task

    async def wait_for_response(
        self,
        task_id: str,
        timeout: Optional[int] = None,
        default_on_timeout: Optional[HITLResponse] = None,
    ) -> HITLResponse:
        """等待审批响应.

        对应WAT HumanProxy等待外部输入。

        Args:
            task_id: 审批任务ID
            timeout: 超时时间（秒），None则使用任务deadline
            default_on_timeout: 超时后的默认响应，None则抛出异常

        Returns:
            HITLResponse: 审批响应

        Raises:
            HITLTaskNotFoundException: 任务不存在
            HITLTimeoutException: 超时且无默认响应
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise HITLTaskNotFoundException(task_id)

            # 如果任务已有响应（提前提交），直接返回
            if task.response is not None:
                return task.response

            # 创建Future等待响应
            future = asyncio.get_event_loop().create_future()
            self._waiters[task_id] = future

        # 计算超时
        timeout_seconds = timeout or settings.DEFAULT_HITL_TIMEOUT_SECONDS
        if task.deadline:
            remaining = (task.deadline - datetime.now(timezone.utc)).total_seconds()
            timeout_seconds = min(timeout_seconds, max(0, remaining))

        try:
            response = await asyncio.wait_for(future, timeout=timeout_seconds)
            return response
        except asyncio.TimeoutError:
            async with self._lock:
                task.status = HITLStatus.TIMEOUT
            if default_on_timeout is not None:
                return default_on_timeout
            raise HITLTimeoutException(task_id)
        finally:
            async with self._lock:
                self._waiters.pop(task_id, None)

    async def submit_response(
        self,
        task_id: str,
        user_id: str,
        response: HITLResponse,
    ) -> HITLTask:
        """用户提交审批响应 - 恢复工作流执行.

        对应WAT HumanProxy接收前端输入。

        Args:
            task_id: 审批任务ID
            user_id: 提交用户ID
            response: 审批响应

        Returns:
            HITLTask: 更新后的任务

        Raises:
            HITLTaskNotFoundException: 任务不存在
            PermissionDeniedException: 无权响应
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise HITLTaskNotFoundException(task_id)

            # 1. 验证权限
            if task.assignee_id and task.assignee_id != user_id:
                from nexus.exceptions import PermissionDeniedException
                raise PermissionDeniedException(
                    resource=f"hitl_task:{task_id}",
                    action="respond",
                )

            # 2. 验证任务状态
            if task.status != HITLStatus.PENDING:
                raise HITLException(
                    f"Task '{task_id}' is already {task.status.value}",
                    code="HITL_TASK_ALREADY_RESPONDED",
                )

            # 3. 更新任务状态
            task.status = HITLStatus.APPROVED if response.approved else HITLStatus.REJECTED
            task.response = response
            task.responded_at = datetime.now(timezone.utc)

        # 4. 广播响应事件
        await self.event_bus.publish(
            {
                "type": "hitl_response",
                "run_id": task.run_id,
                "node_id": task.node_id,
                "task_id": task_id,
                "response": {
                    "approved": response.approved,
                    "selection": response.selection,
                    "input": response.input_data,
                    "correction": response.correction,
                    "notes": response.notes,
                },
            }
        )

        # 5. 唤醒等待的Future
        async with self._lock:
            if task_id in self._waiters:
                future = self._waiters[task_id]
                if not future.done():
                    future.set_result(response)

        return task

    async def get_pending_tasks(
        self,
        assignee_id: Optional[str] = None,
    ) -> list[HITLTask]:
        """获取待审批任务列表."""
        async with self._lock:
            tasks = []
            for task in self._tasks.values():
                if task.status == HITLStatus.PENDING:
                    if assignee_id is None or task.assignee_id == assignee_id:
                        tasks.append(task)
            return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    async def get_task(self, task_id: str) -> HITLTask:
        """获取任务详情."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise HITLTaskNotFoundException(task_id)
            return task

    async def cancel_task(self, task_id: str, user_id: str) -> HITLTask:
        """取消审批任务.

        Args:
            task_id: 审批任务ID
            user_id: 操作用户ID

        Returns:
            HITLTask: 更新后的任务
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise HITLTaskNotFoundException(task_id)

            task.status = HITLStatus.REJECTED
            task.responded_at = datetime.now(timezone.utc)
            task.response = HITLResponse(approved=False, notes="Cancelled by operator")

            # 唤醒等待的Future
            if task_id in self._waiters:
                future = self._waiters[task_id]
                if not future.done():
                    future.set_result(task.response)

        await self.event_bus.publish(
            {
                "type": "hitl_cancelled",
                "run_id": task.run_id,
                "node_id": task.node_id,
                "task_id": task_id,
            }
        )

        return task

    async def get_default_timeout_response(self, task_type: HITLType) -> HITLResponse:
        """获取超时默认响应.

        根据任务类型提供合理的默认行为：
        - APPROVE: 默认拒绝（安全优先）
        - SELECT: 默认选择第一个选项
        - INPUT: 返回空输入
        - CORRECT: 返回空修正
        """
        if task_type == HITLType.APPROVE:
            return HITLResponse(approved=False, notes="Auto-rejected on timeout")
        elif task_type == HITLType.SELECT:
            return HITLResponse(approved=True, selection=None, notes="Auto-selected on timeout")
        elif task_type == HITLType.INPUT:
            return HITLResponse(approved=True, input_data={}, notes="Auto-input on timeout")
        elif task_type == HITLType.CORRECT:
            return HITLResponse(approved=True, correction={}, notes="Auto-corrected on timeout")
        return HITLResponse(approved=False, notes="Default timeout response")

"""人工在环控制器.

基于WAT HumanProxy 升级:
- 从被动等待升级为主动审批流
- 4种审批类型: approve/select/input/correct
- 超时机制 + 默认策略
- 多渠道通知
- **持久化到数据库**（支持跨 Worker 响应）

借鉴LangGraph interrupt() + Camunda Human Task。
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from nexus.config import settings
from nexus.db.database import get_db_session
from nexus.engine.event_bus import EventBus
from nexus.exceptions import HITLException, HITLTaskNotFoundException, HITLTimeoutException

logger = logging.getLogger(__name__)


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
    """审批任务（内存表示）."""

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
    """人工在环控制器.

    跨 Worker 设计:
    - create_task() → 写入 DB + 内存缓存 + EventBus 广播
    - wait_for_response() → 订阅 EventBus（替代 asyncio.Future）
    - submit_response() → 更新 DB + EventBus 广播（Worker/API 均可调用）
    - API 路由响应后通过 EventBus 广播，Worker 通过 Pub/Sub 收到并恢复
    """

    def __init__(
        self,
        event_bus: EventBus,
        notification_service=None,
    ):
        self.event_bus = event_bus
        self.notification = notification_service
        self._tasks: dict[str, HITLTask] = {}  # 内存缓存（Worker 本地）
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

        # 1. 持久化到数据库
        try:
            from nexus.models.hitl import HITLTask as HITLTaskORM
            async with get_db_session() as session:
                db_task = HITLTaskORM(
                    id=task.id,
                    wf_run_id=run_id,
                    node_id=node_id,
                    task_type=task_type.value,
                    title=title,
                    description=description,
                    context=context,
                    assignee_id=assignee_id,
                    status="pending",
                    deadline=deadline,
                )
                session.add(db_task)
        except Exception:
            # DB 写入失败不阻塞（降级到纯内存模式）
            logger.error("Failed to persist HITL task %s to database", task.id, exc_info=True)

        # 2. 缓存到内存
        async with self._lock:
            self._tasks[task.id] = task

        # 3. 推送事件（实时通知前端 + 跨进程广播）
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

        # 4. 多渠道通知
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

        跨 Worker 实现：通过 EventBus 订阅替代 asyncio.Future。
        Worker A 创建任务后进入等待；用户通过 API 提交响应；
        API 进程广播到 Redis Pub/Sub；Worker A 的 EventBus listener 收到后触发 handler。
        """
        # 检查内存缓存（可能已提前响应）
        async with self._lock:
            task = self._tasks.get(task_id)
            if task and task.response is not None:
                return task.response

        # 从数据库检查（跨 Worker 场景）
        if not task or task.response is None:
            try:
                from nexus.models.hitl import HITLTask as HITLTaskORM
                from sqlalchemy import select
                async with get_db_session() as session:
                    stmt = select(HITLTaskORM).where(HITLTaskORM.id == task_id)
                    result = await session.execute(stmt)
                    db_task = result.scalar_one_or_none()
                    if db_task and db_task.response:
                        resp = HITLResponse(**db_task.response)
                        # 缓存到内存
                        if task:
                            task.response = resp
                            task.status = HITLStatus(db_task.status)
                        return resp
                    if not db_task:
                        raise HITLTaskNotFoundException(task_id)
            except HITLTaskNotFoundException:
                raise
            except Exception:
                logger.error("Failed to query HITL task %s from database", task_id, exc_info=True)
                # DB 查询失败继续等待

        # 使用 EventBus 订阅等待响应
        response_event = asyncio.Event()
        response_data: dict[str, Any] = {}

        async def on_response(event: dict[str, Any]) -> None:
            if event.get("task_id") == task_id:
                response_data["response"] = event.get("response")
                response_event.set()

        sub = self.event_bus.subscribe(f"hitl_response:{task_id}", on_response)

        # 计算超时
        timeout_seconds = timeout or settings.DEFAULT_HITL_TIMEOUT_SECONDS
        if task and task.deadline:
            remaining = (task.deadline - datetime.now(timezone.utc)).total_seconds()
            timeout_seconds = min(timeout_seconds, max(0, remaining))

        try:
            await asyncio.wait_for(response_event.wait(), timeout=timeout_seconds)
            return HITLResponse(**response_data["response"])
        except asyncio.TimeoutError:
            async with self._lock:
                if task_id in self._tasks:
                    self._tasks[task_id].status = HITLStatus.TIMEOUT
            if default_on_timeout is not None:
                return default_on_timeout
            raise HITLTimeoutException(task_id)
        finally:
            self.event_bus.unsubscribe(sub)

    async def submit_response(
        self,
        task_id: str,
        user_id: str,
        response: HITLResponse,
    ) -> HITLTask:
        """用户提交审批响应 - 恢复工作流执行.

        对应WAT HumanProxy接收前端输入。
        """
        async with self._lock:
            task = self._tasks.get(task_id)

        # 1. 从数据库验证任务存在（如果不在内存中）
        if not task:
            try:
                from nexus.models.hitl import HITLTask as HITLTaskORM
                from sqlalchemy import select
                async with get_db_session() as session:
                    stmt = select(HITLTaskORM).where(HITLTaskORM.id == task_id)
                    result = await session.execute(stmt)
                    db_task = result.scalar_one_or_none()
                    if not db_task:
                        raise HITLTaskNotFoundException(task_id)
                    # 创建内存缓存
                    task = HITLTask(
                        id=db_task.id,
                        run_id=str(db_task.wf_run_id),
                        node_id=db_task.node_id,
                        task_type=HITLType(db_task.task_type),
                        title=db_task.title,
                        description=db_task.description or "",
                        context=db_task.context or {},
                        assignee_id=str(db_task.assignee_id) if db_task.assignee_id else None,
                        status=HITLStatus(db_task.status),
                        deadline=db_task.deadline,
                        created_at=db_task.created_at,
                    )
                    async with self._lock:
                        self._tasks[task_id] = task
            except HITLTaskNotFoundException:
                raise
            except Exception:
                raise HITLTaskNotFoundException(task_id)

        # 2. 验证权限
        if task.assignee_id and task.assignee_id != user_id:
            from nexus.exceptions import PermissionDeniedException
            raise PermissionDeniedException(
                resource=f"hitl_task:{task_id}",
                action="respond",
            )

        # 3. 验证任务状态
        if task.status != HITLStatus.PENDING:
            raise HITLException(
                f"Task '{task_id}' is already {task.status.value}",
                code="HITL_TASK_ALREADY_RESPONDED",
            )

        # 4. 更新内存状态
        async with self._lock:
            task.status = HITLStatus.APPROVED if response.approved else HITLStatus.REJECTED
            task.response = response
            task.responded_at = datetime.now(timezone.utc)

        # 5. 更新数据库
        try:
            from nexus.models.hitl import HITLTask as HITLTaskORM
            from sqlalchemy import select
            async with get_db_session() as session:
                stmt = select(HITLTaskORM).where(HITLTaskORM.id == task_id)
                result = await session.execute(stmt)
                db_task = result.scalar_one_or_none()
                if db_task:
                    db_task.status = "approved" if response.approved else "rejected"
                    db_task.response = response.__dict__
                    db_task.responded_at = datetime.now(timezone.utc)
        except Exception:
            logger.error("Failed to update HITL task %s in database", task_id, exc_info=True)
            # DB 更新失败不阻塞

        # 6. 广播响应事件（跨进程：Worker 通过 Pub/Sub 收到后恢复）
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
            if task:
                return task

        # 从数据库加载
        try:
            from nexus.models.hitl import HITLTask as HITLTaskORM
            from sqlalchemy import select
            async with get_db_session() as session:
                stmt = select(HITLTaskORM).where(HITLTaskORM.id == task_id)
                result = await session.execute(stmt)
                db_task = result.scalar_one_or_none()
                if not db_task:
                    raise HITLTaskNotFoundException(task_id)
                task = HITLTask(
                    id=db_task.id,
                    run_id=str(db_task.wf_run_id),
                    node_id=db_task.node_id,
                    task_type=HITLType(db_task.task_type),
                    title=db_task.title,
                    description=db_task.description or "",
                    context=db_task.context or {},
                    assignee_id=str(db_task.assignee_id) if db_task.assignee_id else None,
                    status=HITLStatus(db_task.status),
                    response=HITLResponse(**db_task.response) if db_task.response else None,
                    deadline=db_task.deadline,
                    responded_at=db_task.responded_at,
                    created_at=db_task.created_at,
                )
                self._tasks[task_id] = task
                return task
        except HITLTaskNotFoundException:
            raise
        except Exception:
            raise HITLTaskNotFoundException(task_id)

    async def cancel_task(self, task_id: str, user_id: str) -> HITLTask:
        """取消审批任务."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise HITLTaskNotFoundException(task_id)

            task.status = HITLStatus.REJECTED
            task.responded_at = datetime.now(timezone.utc)
            task.response = HITLResponse(approved=False, notes="Cancelled by operator")

        # 更新数据库
        try:
            from nexus.models.hitl import HITLTask as HITLTaskORM
            from sqlalchemy import select
            async with get_db_session() as session:
                stmt = select(HITLTaskORM).where(HITLTaskORM.id == task_id)
                result = await session.execute(stmt)
                db_task = result.scalar_one_or_none()
                if db_task:
                    db_task.status = "rejected"
                    db_task.response = task.response.__dict__
                    db_task.responded_at = datetime.now(timezone.utc)
        except Exception:
            logger.error("Failed to update cancelled HITL task %s in database", task_id, exc_info=True)

        # 广播取消事件
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

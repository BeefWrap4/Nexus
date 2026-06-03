"""异步任务工具模块.

提供安全的后台任务执行包装器，解决以下问题：
- asyncio.create_task 抛出的异常被静默丢弃
- 后台任务崩溃导致 Run 状态永远卡住
- 缺乏统一的错误处理和死信队列机制

用法:
    from nexus.utils.async_tasks import safe_background_task

    # 方式1: 通用包装
    safe_background_task(
        my_coro(),
        task_name="my_task",
        on_error=lambda e: logger.error("Task failed: %s", e),
    )

    # 方式2: 工作流执行专用（自动状态管理）
    safe_background_task(
        runner.execute_from_config(config, payload, run_id),
        task_name=f"workflow_run_{run_id}",
        run_id=run_id,
        tenant_id=tenant_id,
        on_error=on_workflow_error,
    )
"""

from __future__ import annotations

import asyncio
import functools
import logging
import traceback
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# 类型别名
ErrorCallback = Callable[[Exception], Awaitable[None] | None]


def safe_background_task(
    coro: Awaitable[Any],
    *,
    task_name: str = "unnamed",
    on_error: ErrorCallback | None = None,
    run_id: str | None = None,
    tenant_id: str | None = None,
) -> asyncio.Task[Any]:
    """安全地创建后台任务，确保异常被捕获和处理.

    这是 asyncio.create_task 的安全替代方案，解决了以下问题：
    1. 未等待的 Task 异常被静默丢弃（Python 3.8+ 行为）
    2. 异常导致服务状态不一致（如 Run 永远卡在 running）
    3. 缺乏统一的错误日志和监控

    Args:
        coro: 要执行的协程
        task_name: 任务名称（用于日志和调试）
        on_error: 可选的错误回调函数，接收异常对象
        run_id: 可选的关联 Run ID（用于日志上下文）
        tenant_id: 可选的关联 Tenant ID（用于日志上下文）

    Returns:
        创建的 asyncio.Task 对象

    Example:
        >>> safe_background_task(
        ...     execute_workflow(config, payload, run_id),
        ...     task_name="workflow_execution",
        ...     run_id=run_id,
        ...     on_error=lambda e: update_run_status(run_id, "failed", str(e)),
        ... )
    """
    task = asyncio.create_task(
        _wrapped_coro(coro, task_name, on_error, run_id, tenant_id),
        name=task_name,
    )
    return task


async def _wrapped_coro(
    coro: Awaitable[Any],
    task_name: str,
    on_error: ErrorCallback | None,
    run_id: str | None,
    tenant_id: str | None,
) -> Any:
    """包装协程，统一处理异常."""
    context = {
        "task_name": task_name,
        "run_id": run_id,
        "tenant_id": tenant_id,
    }
    context_str = " | ".join(f"{k}={v}" for k, v in context.items() if v is not None)

    try:
        result = await coro
        logger.debug("Background task completed: %s", context_str)
        return result
    except asyncio.CancelledError:
        logger.debug("Background task cancelled: %s", context_str)
        raise  # 取消异常需要重新抛出，让调用方能正确处理
    except Exception as exc:
        logger.error(
            "Background task failed: %s\n%s",
            context_str,
            traceback.format_exc(),
            extra={"run_id": run_id, "tenant_id": tenant_id, "task_name": task_name},
        )

        # 调用错误回调
        if on_error is not None:
            try:
                result = on_error(exc)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception(
                    "Error callback also failed: %s", context_str,
                    extra={"run_id": run_id, "tenant_id": tenant_id},
                )

        # 可选：写入死信队列（异步，不阻塞）
        await _enqueue_dead_letter(run_id, tenant_id, task_name, exc)

        return None


async def _enqueue_dead_letter(
    run_id: str | None,
    tenant_id: str | None,
    task_name: str,
    exc: Exception,
) -> None:
    """将失败的背景任务写入死信队列.

    死信队列用于：
    1. 事后审计和调试
    2. 失败任务重试
    3. 告警触发

    当前实现写入数据库 dead_letter_jobs 表，
    如果数据库不可用则降级为仅日志记录。
    """
    try:
        from nexus.db.database import get_db_session
        from nexus.models import DeadLetterJob

        async with get_db_session() as session:
            job = DeadLetterJob(
                run_id=run_id,
                tenant_id=tenant_id,
                task_name=task_name,
                error_type=type(exc).__name__,
                error_message=str(exc)[:2000],  # 限制长度
                stack_trace=traceback.format_exc()[:4000],
                status="pending",
            )
            session.add(job)
            # get_db_session 上下文会自动 commit
    except ImportError:
        # 模型不可用（如初始化阶段），降级为日志
        logger.warning(
            "Dead letter queue unavailable (model not loaded): %s — %s",
            task_name,
            exc,
        )
    except Exception:
        # 死信队列本身也失败了，只记录日志
        logger.error(
            "Failed to enqueue dead letter: %s — %s",
            task_name,
            exc,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# 快捷函数：工作流执行专用
# ---------------------------------------------------------------------------


def safe_workflow_execution(
    coro: Awaitable[Any],
    run_id: str,
    tenant_id: str,
) -> asyncio.Task[Any]:
    """安全执行工作流，自动管理 Run 状态.

    与 safe_background_task 的区别：
    - 内置 Run 状态更新逻辑（失败时自动设为 failed）
    - 无需手动传入 on_error 回调

    Args:
        coro: 工作流执行协程
        run_id: Run ID
        tenant_id: Tenant ID

    Returns:
        创建的 asyncio.Task 对象
    """
    return safe_background_task(
        coro,
        task_name=f"workflow_run_{run_id}",
        run_id=run_id,
        tenant_id=tenant_id,
        on_error=functools.partial(_on_workflow_error, run_id, tenant_id),
    )


async def _on_workflow_error(run_id: str, tenant_id: str, exc: Exception) -> None:
    """工作流执行失败的默认处理：更新 Run 状态为 failed."""
    try:
        from uuid import UUID

        from nexus.db.database import get_db_session
        from nexus.services.run import RunService

        async with get_db_session() as session:
            run_service = RunService()
            await run_service.update_status(
                session,
                run_id=UUID(run_id),
                tenant_id=UUID(tenant_id),
                status="failed",
                result={"error": str(exc), "error_type": type(exc).__name__},
            )
            logger.info(
                "Run %s status updated to failed after background error", run_id
            )
    except Exception:
        logger.exception(
            "Failed to update Run %s status after background error", run_id
        )

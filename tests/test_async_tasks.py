"""异步任务工具测试 — 覆盖 safe_background_task 安全包装器.

覆盖:
- 成功任务正常返回
- 失败任务被捕获并记录日志
- CancelledError 重新抛出
- on_error 回调正确调用
- 死信队列降级处理
- safe_workflow_execution 快捷函数
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.utils.async_tasks import (
    safe_background_task,
    safe_workflow_execution,
    _wrapped_coro,
    _enqueue_dead_letter,
)


class TestSafeBackgroundTask:
    """测试 safe_background_task 包装器."""

    @pytest.mark.asyncio
    async def test_successful_task_returns_result(self):
        """成功任务应返回原始结果."""
        async def good():
            return "ok"

        task = safe_background_task(good(), task_name="test_task")
        result = await task
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_failing_task_logs_error_and_returns_none(self):
        """失败任务应记录 error 日志并返回 None."""
        async def bad():
            raise ValueError("task failure")

        with patch("nexus.utils.async_tasks.logger") as mock_log:
            with patch("nexus.utils.async_tasks._enqueue_dead_letter", new_callable=AsyncMock):
                task = safe_background_task(bad(), task_name="test_task")
                result = await task
                assert result is None
                mock_log.error.assert_called()

    @pytest.mark.asyncio
    async def test_cancelled_error_re_raised(self):
        """CancelledError 应重新抛出（不做吞没）."""
        async def cancelled():
            raise asyncio.CancelledError()

        task = safe_background_task(cancelled(), task_name="cancellable")
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_on_error_callback_called(self):
        """失败时 on_error 回调应被调用."""
        async def bad():
            raise RuntimeError("boom")

        mock_callback = AsyncMock()
        with patch("nexus.utils.async_tasks._enqueue_dead_letter", new_callable=AsyncMock):
            task = safe_background_task(bad(), task_name="cb_test", on_error=mock_callback)
            await task

        mock_callback.assert_called_once()
        exc = mock_callback.call_args[0][0]
        assert isinstance(exc, RuntimeError)
        assert str(exc) == "boom"

    @pytest.mark.asyncio
    async def test_on_error_callback_sync(self):
        """on_error 回调为同步函数时也应正常工作."""
        async def bad():
            raise RuntimeError("boom")

        errors = []

        def sync_callback(exc):
            errors.append(str(exc))

        with patch("nexus.utils.async_tasks._enqueue_dead_letter", new_callable=AsyncMock):
            task = safe_background_task(bad(), task_name="sync_cb", on_error=sync_callback)
            await task

        assert errors == ["boom"]

    @pytest.mark.asyncio
    async def test_on_error_callback_exception_handled(self):
        """on_error 回调自身抛出异常时也不应中断包装."""
        async def bad():
            raise RuntimeError("original")

        def crashy_callback(exc):
            raise RuntimeError("callback crash")

        with patch("nexus.utils.async_tasks.logger") as mock_log:
            with patch("nexus.utils.async_tasks._enqueue_dead_letter", new_callable=AsyncMock):
                task = safe_background_task(bad(), task_name="crashy_cb", on_error=crashy_callback)
                result = await task
                assert result is None
                mock_log.exception.assert_called()

    @pytest.mark.asyncio
    async def test_run_id_and_tenant_id_in_context(self):
        """run_id 和 tenant_id 应在日志上下文中."""
        async def bad():
            raise RuntimeError("test")

        with patch("nexus.utils.async_tasks.logger") as mock_log:
            with patch("nexus.utils.async_tasks._enqueue_dead_letter", new_callable=AsyncMock):
                task = safe_background_task(
                    bad(), task_name="ctx_test", run_id="run-1", tenant_id="tenant-1"
                )
                await task

            mock_log.error.assert_called()
            call_args = mock_log.error.call_args
            assert call_args.kwargs["extra"]["run_id"] == "run-1"
            assert call_args.kwargs["extra"]["tenant_id"] == "tenant-1"
            assert call_args.kwargs["extra"]["task_name"] == "ctx_test"

    @pytest.mark.asyncio
    async def test_default_task_name(self):
        """默认 task_name 为 "unnamed"."""
        async def good():
            return "ok"

        task = safe_background_task(good())
        result = await task
        assert result == "ok"


class TestSafeWorkflowExecution:
    """测试 safe_workflow_execution 快捷函数."""

    @pytest.mark.asyncio
    async def test_calls_safe_background_task(self):
        """safe_workflow_execution 应委托给 safe_background_task."""
        async def good():
            return "done"

        with patch("nexus.utils.async_tasks.safe_background_task") as mock_safe:
            mock_safe.return_value = asyncio.create_task(asyncio.sleep(0))
            safe_workflow_execution(good(), run_id="r1", tenant_id="t1")

        mock_safe.assert_called_once()
        call_kwargs = mock_safe.call_args.kwargs
        assert call_kwargs["run_id"] == "r1"
        assert call_kwargs["tenant_id"] == "t1"
        assert call_kwargs["task_name"] == "workflow_run_r1"
        assert call_kwargs["on_error"] is not None


class TestEnqueueDeadLetter:
    """测试 _enqueue_dead_letter 死信队列降级."""

    @pytest.mark.asyncio
    async def test_import_error_graceful_degradation(self):
        """模型模块不可用时降级为警告日志."""
        with patch("nexus.utils.async_tasks.logger") as mock_log:
            with patch(
                "nexus.utils.async_tasks._enqueue_dead_letter",
                wraps=_enqueue_dead_letter,
            ) as wrapped:
                # 模拟 ImportError
                with patch(
                    "nexus.db.database.get_db_session",
                    side_effect=ImportError("No module"),
                ):
                    await _enqueue_dead_letter(
                        "r1", "t1", "test", RuntimeError("test err")
                    )

            mock_log.warning.assert_called()

    @pytest.mark.asyncio
    async def test_db_exception_graceful_degradation(self):
        """数据库异常时降级为错误日志."""
        with patch("nexus.utils.async_tasks.logger") as mock_log:
            # DeadLetterJob 在源码内部通过 from nexus.models import DeadLetterJob 导入,
            # 需要同时 patch 该符号路径才能让 ImportError 被绕过,
            # 从而让 get_db_session() 抛出的 Exception 真止进入 except Exception 分支
            with patch(
                "nexus.models.DeadLetterJob",
                create=True,
            ), patch(
                "nexus.db.database.get_db_session",
                side_effect=Exception("DB connection failed"),
            ):
                await _enqueue_dead_letter(
                    "r1", "t1", "test", RuntimeError("test err")
                )

            mock_log.error.assert_called()

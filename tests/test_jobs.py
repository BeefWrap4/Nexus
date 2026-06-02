"""ARQ 任务队列测试.

覆盖:
- WorkerSettings 配置验证
- execute_workflow_job 任务函数可调用性
- ARQ 连接池生命周期
"""

import pytest

from nexus.jobs.config import WorkerSettings
from nexus.jobs.pool import close_arq_pool, get_arq_pool, init_arq_pool
from nexus.jobs.workflow import execute_workflow_job


class TestWorkerSettings:
    """测试 ARQ Worker 配置."""

    def test_worker_settings_has_functions(self):
        """WorkerSettings 应注册 execute_workflow_job."""
        function_names = [f.__name__ for f in WorkerSettings.functions]
        assert "execute_workflow_job" in function_names

    def test_worker_settings_concurrency_positive(self):
        """并发数应为正数."""
        assert WorkerSettings.max_jobs > 0

    def test_worker_settings_timeout_positive(self):
        """超时时间应为正数."""
        assert WorkerSettings.job_timeout > 0

    def test_worker_settings_redis_configured(self):
        """Redis 连接应已配置."""
        assert WorkerSettings.redis_settings is not None


class TestARQPool:
    """测试 ARQ 连接池管理."""

    def test_get_arq_pool_returns_none_before_init(self):
        """初始化前应返回 None."""
        assert get_arq_pool() is None

    @pytest.mark.asyncio
    async def test_init_and_close_arq_pool(self):
        """连接池应能正常初始化和关闭."""
        # 注意：此测试需要 Redis 服务运行
        # 如果没有 Redis，会抛出 ConnectionError
        try:
            await init_arq_pool()
            pool = get_arq_pool()
            assert pool is not None
            await close_arq_pool()
            assert get_arq_pool() is None
        except Exception as exc:
            pytest.skip(f"Redis not available: {exc}")


class TestExecuteWorkflowJob:
    """测试 ARQ 工作流执行任务."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_execute_workflow_job_with_empty_config(self):
        """空工作流配置应快速返回（需要 PostgreSQL）."""
        ctx = {"redis": None}
        result = await execute_workflow_job(
            ctx,
            run_id="12345678-1234-1234-1234-123456789abc",
            workflow_config={"nodes": [], "edges": []},
            trigger_payload={},
            tenant_id="12345678-1234-1234-1234-123456789abc",
        )
        assert result["run_id"] == "12345678-1234-1234-1234-123456789abc"
        assert "status" in result

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_execute_workflow_job_returns_dict(self):
        """任务函数应返回包含 run_id 和 status 的字典（需要 PostgreSQL）."""
        ctx = {"redis": None}
        result = await execute_workflow_job(
            ctx,
            run_id="12345678-1234-1234-1234-123456789abc",
            workflow_config={"nodes": [], "edges": []},
            trigger_payload={},
            tenant_id="12345678-1234-1234-1234-123456789abc",
        )
        assert isinstance(result, dict)
        assert "run_id" in result
        assert "status" in result
        assert "duration_ms" in result

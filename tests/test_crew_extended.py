"""Crew 扩展测试 — 覆盖率提升 82% → 90%+.

覆盖之前未测试的代码路径:
- _delegate 完整 LLM 分解逻辑
- _aggregate 无 Manager / Manager 异常 fallback
- _run_worker 无 Workers 场景
- _run_workers_parallel 异常处理
- Sequential/Parallel 无 Manager 聚合
- _trim_shared_context JSON 异常
"""

from __future__ import annotations

import json

from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.agent.base import AgentConfig, Task
from nexus.agent.crew import (
    Crew,
    CrewConfig,
    CrewMode,
    CrewTask,
    CrewWorkerResult,
)
from nexus.agent.llm_client import LLMResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_worker_factory():
    """工厂: 创建可配置的 mock Worker."""
    def _make(name="worker", output="Result", success=True, side_effect=None):
        agent = MagicMock()
        agent.config = AgentConfig(name=name)
        agent.execute = AsyncMock(
            side_effect=side_effect
            or (
                lambda task, context=None: MagicMock(
                    output=output,
                    reasoning="",
                    tool_calls=[],
                    status="success" if success else "failed",
                )
            )
        )
        return agent
    return _make


@pytest.fixture
def mock_manager():
    """创建 mock Manager Agent."""
    agent = MagicMock()
    agent.config = AgentConfig(name="manager")
    agent.llm_client = MagicMock()
    agent.execute = AsyncMock(
        return_value=MagicMock(
            output="Final aggregated answer",
            reasoning="Aggregated reasoning",
            tool_calls=[],
            status="success",
        )
    )
    return agent


# ---------------------------------------------------------------------------
# _delegate 任务分解测试
# ---------------------------------------------------------------------------

class TestCrewDelegate:
    """测试 _delegate 任务分解方法 (lines 497-569)."""

    @pytest.mark.asyncio
    async def test_delegate_without_manager_equal_distribution(self):
        """无 Manager 时，应为每个 Worker 分配相同任务."""
        worker_a = MagicMock()
        worker_a.config = AgentConfig(name="w_a")
        worker_b = MagicMock()
        worker_b.config = AgentConfig(name="w_b")

        crew = Crew(manager=None, workers=[worker_a, worker_b])

        sub_tasks = await crew._delegate("Main task", {})

        assert len(sub_tasks) == 2
        assert all(t.description == "Main task" for t in sub_tasks)
        assert {t.assigned_to for t in sub_tasks} == {"w_a", "w_b"}

    @pytest.mark.asyncio
    async def test_delegate_auto_delegate_disabled(self, mock_manager):
        """关闭 auto_delegate 时，应为每个 Worker 分配相同任务."""
        worker = MagicMock()
        worker.config = AgentConfig(name="w1")

        config = CrewConfig(auto_delegate=False)
        crew = Crew(manager=mock_manager, workers=[worker], config=config)

        sub_tasks = await crew._delegate("Main task", {})

        assert len(sub_tasks) == 1
        assert sub_tasks[0].description == "Main task"
        assert sub_tasks[0].assigned_to == "w1"

    @pytest.mark.asyncio
    async def test_delegate_no_manager_no_auto_delegate(self):
        """无 Manager 且无 auto_delegate 时，也应等量分配."""
        worker = MagicMock()
        worker.config = AgentConfig(name="w1")

        config = CrewConfig(auto_delegate=False)
        crew = Crew(manager=None, workers=[worker], config=config)

        sub_tasks = await crew._delegate("Main task", {})

        assert len(sub_tasks) == 1
        assert sub_tasks[0].description == "Main task"

    @pytest.mark.asyncio
    async def test_delegate_llm_successful_json_array(self, mock_manager):
        """LLM 返回正确的 JSON 数组时，应正确解析子任务."""
        worker_a = MagicMock()
        worker_a.config = AgentConfig(name="researcher")
        worker_b = MagicMock()
        worker_b.config = AgentConfig(name="analyst")

        mock_manager.llm_client.call = AsyncMock(
            return_value=LLMResponse(
                content=json.dumps([
                    {"description": "Research the topic", "assigned_to": "researcher"},
                    {"description": "Analyze findings", "assigned_to": "analyst"},
                ]),
                model="gpt-4o",
                usage={},
            )
        )

        config = CrewConfig(auto_delegate=True)
        crew = Crew(manager=mock_manager, workers=[worker_a, worker_b], config=config)

        # mock_manager.llm_client 已设置，_delegate 会直接用而不会 fallback 到 LLMClient()
        sub_tasks = await crew._delegate("Complex analysis task", {})

        assert len(sub_tasks) == 2
        assert sub_tasks[0].description == "Research the topic"
        assert sub_tasks[0].assigned_to == "researcher"
        assert sub_tasks[1].description == "Analyze findings"
        assert sub_tasks[1].assigned_to == "analyst"

    @pytest.mark.asyncio
    async def test_delegate_llm_json_with_tasks_key(self, mock_manager):
        """LLM 返回 {"tasks": [...]} 格式时，应正确提取."""
        worker = MagicMock()
        worker.config = AgentConfig(name="worker1")

        mock_manager.llm_client.call = AsyncMock(
            return_value=LLMResponse(
                content=json.dumps({
                    "tasks": [
                        {"description": "Sub task 1", "assigned_to": "worker1"},
                        {"description": "Sub task 2", "assigned_to": "worker1"},
                    ]
                }),
                model="gpt-4o",
                usage={},
            )
        )

        crew = Crew(manager=mock_manager, workers=[worker])

        sub_tasks = await crew._delegate("Main task", {})

        assert len(sub_tasks) == 2
        assert sub_tasks[0].description == "Sub task 1"
        assert sub_tasks[1].description == "Sub task 2"

    @pytest.mark.asyncio
    async def test_delegate_llm_json_decode_error_fallback(self, mock_manager):
        """LLM 返回非法 JSON 时，应 fallback 到等量分配."""
        worker = MagicMock()
        worker.config = AgentConfig(name="w1")

        mock_manager.llm_client.call = AsyncMock(
            return_value=LLMResponse(
                content="Not valid JSON at all!!!",
                model="gpt-4o",
                usage={},
            )
        )

        crew = Crew(manager=mock_manager, workers=[worker])

        sub_tasks = await crew._delegate("Main task", {})

        assert len(sub_tasks) == 1
        assert sub_tasks[0].description == "Main task"
        assert sub_tasks[0].assigned_to == "w1"

    @pytest.mark.asyncio
    async def test_delegate_llm_returns_non_list_dict(self, mock_manager):
        """LLM 返回单个 dict 对象（非数组）时，应包装为列表."""
        worker = MagicMock()
        worker.config = AgentConfig(name="w1")

        mock_manager.llm_client.call = AsyncMock(
            return_value=LLMResponse(
                content=json.dumps({"description": "Single task", "assigned_to": "w1"}),
                model="gpt-4o",
                usage={},
            )
        )

        crew = Crew(manager=mock_manager, workers=[worker])

        sub_tasks = await crew._delegate("Main task", {})

        assert len(sub_tasks) == 1
        assert sub_tasks[0].description == "Single task"

    @pytest.mark.asyncio
    async def test_delegate_empty_tasks_fallback(self, mock_manager):
        """LLM 返回空任务列表时，应 fallback 到等量分配."""
        worker = MagicMock()
        worker.config = AgentConfig(name="w1")

        mock_manager.llm_client.call = AsyncMock(
            return_value=LLMResponse(
                content=json.dumps([{"description": "", "assigned_to": "w1"}]),
                model="gpt-4o",
                usage={},
            )
        )

        crew = Crew(manager=mock_manager, workers=[worker])

        sub_tasks = await crew._delegate("Main task", {})

        # 空 description 的任务被过滤，fallback 到等量分配
        assert len(sub_tasks) == 1
        assert sub_tasks[0].description == "Main task"

    @pytest.mark.asyncio
    async def test_delegate_llm_exception_fallback(self, mock_manager):
        """LLM 调用抛出异常时，应 fallback 到等量分配."""
        worker = MagicMock()
        worker.config = AgentConfig(name="w1")

        mock_manager.llm_client.call = AsyncMock(
            side_effect=Exception("LLM API error")
        )

        crew = Crew(manager=mock_manager, workers=[worker])

        sub_tasks = await crew._delegate("Main task", {})

        assert len(sub_tasks) == 1
        assert sub_tasks[0].description == "Main task"
        assert sub_tasks[0].assigned_to == "w1"


# ---------------------------------------------------------------------------
# _aggregate 结果聚合测试
# ---------------------------------------------------------------------------

class TestCrewAggregate:
    """测试 _aggregate 结果聚合方法 (lines 578-647)."""

    @pytest.mark.asyncio
    async def test_aggregate_without_manager_simple_concat(self):
        """无 Manager 时，应简单拼接 Worker 输出."""
        crew = Crew(manager=None)

        results = [
            CrewWorkerResult(
                worker_name="w1",
                task=CrewTask(description="T1"),
                output="Output 1",
                success=True,
            ),
            CrewWorkerResult(
                worker_name="w2",
                task=CrewTask(description="T2"),
                output="Output 2",
                success=True,
            ),
        ]

        aggregated = await crew._aggregate("Original task", results, {})

        assert "w1" in aggregated.output
        assert "Output 1" in aggregated.output
        assert "w2" in aggregated.output
        assert "Output 2" in aggregated.output
        assert aggregated.worker_name == "aggregation"
        assert aggregated.success is True

    @pytest.mark.asyncio
    async def test_aggregate_without_manager_all_failed(self):
        """无 Manager 且所有 Worker 失败时，返回提示信息."""
        crew = Crew(manager=None)

        results = [
            CrewWorkerResult(
                worker_name="w1",
                task=CrewTask(description="T1"),
                success=False,
                error="Something broke",
            ),
        ]

        aggregated = await crew._aggregate("Original task", results, {})

        assert "No successful worker results" in aggregated.output
        assert aggregated.success is True

    @pytest.mark.asyncio
    async def test_aggregate_manager_exception_fallback(self, mock_manager):
        """Manager 聚合抛出异常时，应 fallback 到简单拼接."""
        crew = Crew(manager=mock_manager)

        results = [
            CrewWorkerResult(
                worker_name="w1",
                task=CrewTask(description="T1"),
                output="Worker output",
                success=True,
            ),
        ]

        # Manager 执行时抛出异常
        mock_manager.execute = AsyncMock(side_effect=Exception("Manager crash"))

        aggregated = await crew._aggregate("Original task", results, {})

        assert "w1" in aggregated.output
        assert "Worker output" in aggregated.output
        assert aggregated.success is True

    @pytest.mark.asyncio
    async def test_aggregate_with_failed_workers(self, mock_manager):
        """混合成功/失败 Worker 时，Manager 收到失败信息."""
        crew = Crew(manager=mock_manager)

        results = [
            CrewWorkerResult(
                worker_name="w1",
                task=CrewTask(description="T1"),
                output="OK",
                success=True,
            ),
            CrewWorkerResult(
                worker_name="w2",
                task=CrewTask(description="T2"),
                success=False,
                error="Worker error",
            ),
        ]

        aggregated = await crew._aggregate("Original task", results, {})

        assert aggregated.output == "Final aggregated answer"
        # Manager.execute 应被调用，且 prompt 中包含成功和失败信息
        call_args = mock_manager.execute.call_args
        prompt = call_args[0][0].description
        assert "Worker outputs" in prompt
        assert "ERROR: Worker error" in prompt


# ---------------------------------------------------------------------------
# _run_worker 测试
# ---------------------------------------------------------------------------

class TestCrewRunWorker:
    """测试 _run_worker Worker 执行方法 (lines 431-481)."""

    @pytest.mark.asyncio
    async def test_run_worker_no_workers_available(self):
        """无任何 Worker 时，应返回失败结果."""
        crew = Crew(workers=[])  # 空 workers dict

        task = CrewTask(description="Test task", assigned_to="anyone")
        result = await crew._run_worker(task, {})

        assert result.success is False
        assert "No workers available" in result.error
        assert result.worker_name == "none"

    @pytest.mark.asyncio
    async def test_run_worker_fallback_to_first_available(self):
        """指定 Worker 不存在时，应 fallback 到第一个可用 Worker."""
        worker = MagicMock()
        worker.config = AgentConfig(name="real_worker")
        worker.execute = AsyncMock(
            return_value=MagicMock(
                output="Hello from real_worker",
                reasoning="",
                tool_calls=[],
                status="success",
            )
        )

        crew = Crew(workers=[worker])
        # 构造 task 时 assigned_to 为不存在的 worker
        task = CrewTask(description="Test task", assigned_to="nonexistent")
        result = await crew._run_worker(task, {})

        assert result.success is True
        assert result.worker_name == "real_worker"
        assert "Hello" in result.output

    @pytest.mark.asyncio
    async def test_run_worker_exception_handling(self):
        """Worker 执行抛出异常时，应返回失败结果."""
        worker = MagicMock()
        worker.config = AgentConfig(name="crashy")
        worker.execute = AsyncMock(side_effect=RuntimeError("Boom!"))

        crew = Crew(workers=[worker])

        task = CrewTask(description="Test", assigned_to="crashy")
        result = await crew._run_worker(task, {})

        assert result.success is False
        assert "Boom!" in result.error
        assert result.worker_name == "crashy"


# ---------------------------------------------------------------------------
# _run_workers_parallel 测试
# ---------------------------------------------------------------------------

class TestCrewRunWorkersParallel:
    """测试 _run_workers_parallel 并发执行方法 (lines 398-429)."""

    @pytest.mark.asyncio
    async def test_run_workers_parallel_exception_handling(self):
        """Worker 并发执行中异常应被捕获并返回失败结果."""
        worker = MagicMock()
        worker.config = AgentConfig(name="worker1")
        worker.execute = AsyncMock(
            side_effect=RuntimeError("Parallel crash")
        )

        crew = Crew(workers=[worker])

        tasks = [CrewTask(description="Task", assigned_to="worker1")]
        results = await crew._run_workers_parallel(tasks, {})

        assert len(results) == 1
        assert results[0].success is False
        assert "Parallel crash" in results[0].error

    @pytest.mark.asyncio
    async def test_run_workers_parallel_unhandled_exception(self):
        """_run_worker 抛出未捕获异常时，asyncio.gather 应将其包装为失败结果 (line 418)."""
        worker = MagicMock()
        worker.config = AgentConfig(name="worker1")

        # 创建子类使 _run_worker 抛出未捕获异常（绕过内部 try/except）
        class BrokenCrew(Crew):
            async def _run_worker(self, task, context):
                raise RuntimeError("Unhandled internal crash")

        crew = BrokenCrew(workers=[worker])

        tasks = [CrewTask(description="Task", assigned_to="worker1")]
        results = await crew._run_workers_parallel(tasks, {})

        assert len(results) == 1
        assert results[0].success is False
        assert results[0].worker_name == "unknown"
        assert "Unhandled internal crash" in results[0].error


# ---------------------------------------------------------------------------
# Sequential / Parallel 无 Manager 测试
# ---------------------------------------------------------------------------

class TestCrewNoManager:
    """测试无 Manager 时的 Sequential / Parallel 模式集中聚合."""

    @pytest.mark.asyncio
    async def test_sequential_without_manager_concat(self):
        """Sequential 模式无 Manager 时，应拼接所有 Worker 输出."""
        worker_a = MagicMock()
        worker_a.config = AgentConfig(name="w_a")
        worker_a.execute = AsyncMock(
            return_value=MagicMock(
                output="Output A",
                reasoning="",
                tool_calls=[],
                status="success",
            )
        )

        worker_b = MagicMock()
        worker_b.config = AgentConfig(name="w_b")
        worker_b.execute = AsyncMock(
            return_value=MagicMock(
                output="Output B",
                reasoning="",
                tool_calls=[],
                status="success",
            )
        )

        config = CrewConfig(mode=CrewMode.SEQUENTIAL)
        crew = Crew(manager=None, workers=[worker_a, worker_b], config=config)

        result = await crew.execute("Sequential task")

        assert len(result.worker_results) == 2
        assert "w_a" in result.output
        assert "Output A" in result.output
        assert "w_b" in result.output
        assert "Output B" in result.output
        assert result.manager_reasoning == ""

    @pytest.mark.asyncio
    async def test_parallel_without_manager_concat(self):
        """Parallel 模式无 Manager 时，应拼接所有 Worker 输出."""
        worker_a = MagicMock()
        worker_a.config = AgentConfig(name="w_a")
        worker_a.execute = AsyncMock(
            return_value=MagicMock(
                output="Output A",
                reasoning="",
                tool_calls=[],
                status="success",
            )
        )

        worker_b = MagicMock()
        worker_b.config = AgentConfig(name="w_b")
        worker_b.execute = AsyncMock(
            return_value=MagicMock(
                output="Output B",
                reasoning="",
                tool_calls=[],
                status="success",
            )
        )

        config = CrewConfig(mode=CrewMode.PARALLEL)
        crew = Crew(manager=None, workers=[worker_a, worker_b], config=config)

        result = await crew.execute("Parallel task")

        assert len(result.worker_results) == 2
        assert "w_a" in result.output
        assert "Output A" in result.output
        assert "w_b" in result.output
        assert "Output B" in result.output
        assert result.manager_reasoning == ""


# ---------------------------------------------------------------------------
# _trim_shared_context 测试
# ---------------------------------------------------------------------------

class TestCrewTrimSharedContext:
    """测试 _trim_shared_context (lines 652-668)."""

    def test_trim_shared_context_json_exception(self):
        """JSON 序列化失败时不应抛出异常."""
        config = CrewConfig(max_shared_context_size=1)

        crew = Crew(config=config)

        # 放置不可序列化的对象
        class Unserializable:
            pass

        crew.shared_context["bad_key"] = Unserializable()

        # 不应抛出异常
        crew._trim_shared_context()
        # shared_context 保持不变
        assert "bad_key" in crew.shared_context


# ---------------------------------------------------------------------------
# CrewTask / CrewWorkerResult 数据类测试
# ---------------------------------------------------------------------------

class TestCrewDataclasses:
    """测试 Crew 数据类的默认值和构造."""

    def test_crew_task_defaults(self):
        """CrewTask 应有正确的默认值."""
        task = CrewTask(description="Test")
        assert task.assigned_to == ""
        assert task.expected_output == ""
        assert task.context == {}

    def test_crew_task_full(self):
        """CrewTask 完整构造."""
        task = CrewTask(
            description="Full task",
            assigned_to="agent1",
            expected_output="Summary",
            context={"key": "value"},
        )
        assert task.description == "Full task"
        assert task.assigned_to == "agent1"
        assert task.expected_output == "Summary"
        assert task.context == {"key": "value"}

    def test_crew_worker_result_defaults(self):
        """CrewWorkerResult 应有正确的默认值."""
        task = CrewTask(description="T")
        result = CrewWorkerResult(worker_name="w", task=task)
        assert result.output == ""
        assert result.reasoning == ""
        assert result.tool_calls == []
        assert result.success is True
        assert result.error == ""

    def test_crew_result_full(self):
        """CrewResult 完整构造."""
        result = CrewWorkerResult(
            worker_name="w",
            task=CrewTask(description="T"),
            output="Out",
            reasoning="R",
        )
        crew_result = result.__class__  # just checking CrewResult separately
        # Actually test CrewResult
        from nexus.agent.crew import CrewResult
        cr = CrewResult(
            output="Final",
            manager_reasoning="Reason",
            worker_results=[result],
            tool_calls=[{"tool": "x"}],
            shared_context={"key": "val"},
        )
        assert cr.output == "Final"
        assert cr.manager_reasoning == "Reason"
        assert len(cr.worker_results) == 1
        assert cr.tool_calls == [{"tool": "x"}]
        assert cr.shared_context == {"key": "val"}

    def test_crew_result_defaults(self):
        """CrewResult 应有正确的默认值."""
        from nexus.agent.crew import CrewResult
        cr = CrewResult(output="Test")
        assert cr.manager_reasoning == ""
        assert cr.worker_results == []
        assert cr.tool_calls == []
        assert cr.shared_context == {}

"""Crew 多 Agent 协作测试 — Phase 10.

覆盖：
- 三种协作模式: Hierarchical / Sequential / Parallel
- Agent 间共享上下文
- EventBus 事件广播
- Worker 失败优雅降级
- CrewNodeExecutor Workflow 集成
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.agent.base import AgentConfig, BaseAgent, Task
from nexus.agent.crew import (
    Crew,
    CrewConfig,
    CrewMode,
    CrewResult,
    CrewTask,
    CrewWorkerResult,
)
from nexus.agent.llm_client import LLMResponse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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


@pytest.fixture
def mock_worker(name="worker"):
    """创建 mock Worker Agent."""
    agent = MagicMock()
    agent.config = AgentConfig(name=name)
    agent.execute = AsyncMock(
        return_value=MagicMock(
            output=f"Result from {name}",
            reasoning=f"Reasoning from {name}",
            tool_calls=[],
            status="success",
        )
    )
    return agent


@pytest.fixture
def mock_event_bus():
    """创建 mock EventBus."""
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


# ---------------------------------------------------------------------------
# Phase 4 迁移: 基础 Crew 协作
# ---------------------------------------------------------------------------

class TestCrewCollaboration:
    """测试 Crew Manager-Worker 协作（Hierarchical 模式）."""

    @pytest.mark.asyncio
    async def test_crew_execution(self, mock_manager, mock_worker):
        """Crew 应能分解任务并聚合结果."""
        crew = Crew(manager=mock_manager, workers=[mock_worker])

        with patch.object(crew, "_delegate", new_callable=AsyncMock) as mock_delegate:
            mock_delegate.return_value = [
                CrewTask(description="Research topic", assigned_to="worker")
            ]

            result = await crew.execute("Analyze this topic")

        assert result.output == "Final aggregated answer"
        assert len(result.worker_results) == 1
        assert result.worker_results[0].output == "Result from worker"

    @pytest.mark.asyncio
    async def test_crew_worker_fallback(self, mock_manager, mock_worker):
        """指定 Worker 不存在时应 fallback 到第一个可用 Worker."""
        crew = Crew(manager=mock_manager, workers=[mock_worker])

        with patch.object(crew, "_delegate", new_callable=AsyncMock) as mock_delegate:
            mock_delegate.return_value = [
                CrewTask(description="Task", assigned_to="nonexistent")
            ]

            result = await crew.execute("Test")

        # fallback 到第一个可用 worker，worker_name 反映实际执行的 worker
        assert result.worker_results[0].worker_name == "worker"
        assert result.worker_results[0].output == "Result from worker"

    @pytest.mark.asyncio
    async def test_crew_worker_failure_handling(self, mock_manager):
        """Worker 失败时应记录错误，不影响整体执行."""
        failing_worker = MagicMock()
        failing_worker.config = AgentConfig(name="failing_worker")
        failing_worker.execute = AsyncMock(side_effect=Exception("Worker crashed"))

        crew = Crew(manager=mock_manager, workers=[failing_worker])

        with patch.object(crew, "_delegate", new_callable=AsyncMock) as mock_delegate:
            mock_delegate.return_value = [
                CrewTask(description="Task", assigned_to="failing_worker")
            ]

            result = await crew.execute("Test")

        assert not result.worker_results[0].success
        assert "Worker crashed" in result.worker_results[0].error
        # Manager 仍应尝试聚合
        assert result.output == "Final aggregated answer"


# ---------------------------------------------------------------------------
# Phase 10: 三种协作模式
# ---------------------------------------------------------------------------

class TestCrewModes:
    """测试三种协作模式."""

    @pytest.mark.asyncio
    async def test_crew_sequential_execution(self, mock_manager):
        """Sequential 模式: Worker A 输出作为 Worker B 上下文."""
        worker_a = MagicMock()
        worker_a.config = AgentConfig(name="worker_a")
        worker_a.execute = AsyncMock(
            return_value=MagicMock(
                output="Step A completed",
                reasoning="",
                tool_calls=[],
                status="success",
            )
        )

        worker_b = MagicMock()
        worker_b.config = AgentConfig(name="worker_b")
        worker_b.execute = AsyncMock(
            return_value=MagicMock(
                output="Step B completed using A's result",
                reasoning="",
                tool_calls=[],
                status="success",
            )
        )

        config = CrewConfig(mode=CrewMode.SEQUENTIAL)
        crew = Crew(
            manager=mock_manager,
            workers=[worker_a, worker_b],
            config=config,
        )

        result = await crew.execute("Sequential task")

        assert result.output == "Final aggregated answer"
        assert len(result.worker_results) == 2
        assert result.worker_results[0].output == "Step A completed"
        assert result.worker_results[1].output == "Step B completed using A's result"

        # 验证 Worker B 收到了包含 Worker A 输出的任务描述
        call_args = worker_b.execute.call_args
        task_arg = call_args[0][0]
        assert "Step A completed" in task_arg.description

    @pytest.mark.asyncio
    async def test_crew_parallel_execution(self, mock_manager):
        """Parallel 模式: 多个 Worker 同时执行."""
        worker_1 = MagicMock()
        worker_1.config = AgentConfig(name="worker_1")
        worker_1.execute = AsyncMock(
            return_value=MagicMock(
                output="Result 1",
                reasoning="",
                tool_calls=[],
                status="success",
            )
        )

        worker_2 = MagicMock()
        worker_2.config = AgentConfig(name="worker_2")
        worker_2.execute = AsyncMock(
            return_value=MagicMock(
                output="Result 2",
                reasoning="",
                tool_calls=[],
                status="success",
            )
        )

        config = CrewConfig(mode=CrewMode.PARALLEL)
        crew = Crew(
            manager=mock_manager,
            workers=[worker_1, worker_2],
            config=config,
        )

        result = await crew.execute("Parallel task")

        assert len(result.worker_results) == 2
        assert result.worker_results[0].output == "Result 1"
        assert result.worker_results[1].output == "Result 2"

    @pytest.mark.asyncio
    async def test_crew_hierarchical_delegation(self, mock_manager):
        """Hierarchical 模式: Manager 正确分解任务."""
        worker = MagicMock()
        worker.config = AgentConfig(name="researcher")
        worker.execute = AsyncMock(
            return_value=MagicMock(
                output="Research done",
                reasoning="",
                tool_calls=[],
                status="success",
            )
        )

        config = CrewConfig(mode=CrewMode.HIERARCHICAL, auto_delegate=True)
        crew = Crew(
            manager=mock_manager,
            workers=[worker],
            config=config,
        )

        with patch.object(crew, "_delegate", new_callable=AsyncMock) as mock_delegate:
            mock_delegate.return_value = [
                CrewTask(description="Research subtask", assigned_to="researcher")
            ]

            result = await crew.execute("Research and analyze")

        assert result.output == "Final aggregated answer"
        mock_delegate.assert_called_once()


# ---------------------------------------------------------------------------
# Phase 10: Shared Context
# ---------------------------------------------------------------------------

class TestCrewSharedContext:
    """测试 Agent 间共享上下文."""

    @pytest.mark.asyncio
    async def test_crew_shared_context_sequential(self, mock_manager):
        """Sequential 模式下共享上下文应正确传递."""
        worker_a = MagicMock()
        worker_a.config = AgentConfig(name="worker_a")
        worker_a.execute = AsyncMock(
            return_value=MagicMock(
                output="A output",
                reasoning="",
                tool_calls=[],
                status="success",
            )
        )

        worker_b = MagicMock()
        worker_b.config = AgentConfig(name="worker_b")
        worker_b.execute = AsyncMock(
            return_value=MagicMock(
                output="B output",
                reasoning="",
                tool_calls=[],
                status="success",
            )
        )

        config = CrewConfig(mode=CrewMode.SEQUENTIAL, shared_context_enabled=True)
        crew = Crew(
            manager=mock_manager,
            workers=[worker_a, worker_b],
            config=config,
        )

        result = await crew.execute("Test shared context")

        # Worker B 的 context 中应包含 shared_context
        call_args = worker_b.execute.call_args
        context_arg = call_args[1]["context"]
        assert "shared_context" in context_arg

        # 结果中应包含 worker_outputs
        assert "worker_outputs" in result.shared_context

    @pytest.mark.asyncio
    async def test_crew_shared_context_parallel(self, mock_manager):
        """Parallel 模式下共享上下文应包含所有 Worker 输出."""
        worker_1 = MagicMock()
        worker_1.config = AgentConfig(name="worker_1")
        worker_1.execute = AsyncMock(
            return_value=MagicMock(
                output="Output 1",
                reasoning="",
                tool_calls=[],
                status="success",
            )
        )

        worker_2 = MagicMock()
        worker_2.config = AgentConfig(name="worker_2")
        worker_2.execute = AsyncMock(
            return_value=MagicMock(
                output="Output 2",
                reasoning="",
                tool_calls=[],
                status="success",
            )
        )

        config = CrewConfig(mode=CrewMode.PARALLEL, shared_context_enabled=True)
        crew = Crew(
            manager=mock_manager,
            workers=[worker_1, worker_2],
            config=config,
        )

        result = await crew.execute("Test parallel shared context")

        # Worker 输出应写入 shared_context
        worker_outputs = result.shared_context.get("worker_outputs", {})
        assert "worker_1" in worker_outputs
        assert "worker_2" in worker_outputs
        assert worker_outputs["worker_1"]["output"] == "Output 1"
        assert worker_outputs["worker_2"]["output"] == "Output 2"


# ---------------------------------------------------------------------------
# Phase 10: EventBus
# ---------------------------------------------------------------------------

class TestCrewEventBus:
    """测试 EventBus 事件广播."""

    @pytest.mark.asyncio
    async def test_crew_event_bus_publish(self, mock_manager, mock_worker, mock_event_bus):
        """Crew 执行应通过 EventBus 发布 crew_step 事件."""
        config = CrewConfig(mode=CrewMode.HIERARCHICAL)
        crew = Crew(
            manager=mock_manager,
            workers=[mock_worker],
            config=config,
            event_bus=mock_event_bus,
            crew_id="crew-123",
        )

        with patch.object(crew, "_delegate", new_callable=AsyncMock) as mock_delegate:
            mock_delegate.return_value = [
                CrewTask(description="Task", assigned_to="worker")
            ]
            await crew.execute("Test event bus")

        # 验证 EventBus.publish 被调用，且包含 crew_step 事件
        publish_calls = mock_event_bus.publish.call_args_list
        event_types = [call[0][0].get("type") for call in publish_calls]
        assert "crew_step" in event_types

        # 验证 crew_id 正确传递
        crew_events = [call[0][0] for call in publish_calls if call[0][0].get("type") == "crew_step"]
        assert all(e.get("crew_id") == "crew-123" for e in crew_events)

    @pytest.mark.asyncio
    async def test_crew_event_bus_failure_ignored(self, mock_manager, mock_worker):
        """EventBus 发布失败不应阻塞主流程."""
        failing_bus = MagicMock()
        failing_bus.publish = AsyncMock(side_effect=Exception("Bus error"))

        config = CrewConfig(mode=CrewMode.HIERARCHICAL)
        crew = Crew(
            manager=mock_manager,
            workers=[mock_worker],
            config=config,
            event_bus=failing_bus,
        )

        with patch.object(crew, "_delegate", new_callable=AsyncMock) as mock_delegate:
            mock_delegate.return_value = [
                CrewTask(description="Task", assigned_to="worker")
            ]
            # 不应抛出异常
            result = await crew.execute("Test with failing bus")

        assert result.output == "Final aggregated answer"


# ---------------------------------------------------------------------------
# Phase 10: Crew Config
# ---------------------------------------------------------------------------

class TestCrewConfig:
    """测试 Crew 配置选项."""

    @pytest.mark.asyncio
    async def test_crew_config_defaults(self):
        """默认配置应为 Hierarchical 模式."""
        config = CrewConfig()
        assert config.mode == CrewMode.HIERARCHICAL
        assert config.max_workers == 5
        assert config.shared_context_enabled is True
        assert config.auto_delegate is True

    @pytest.mark.asyncio
    async def test_crew_without_manager_parallel_fallback(self, mock_worker):
        """无 Manager 时 Hierarchical 应 fallback 到 Parallel."""
        config = CrewConfig(mode=CrewMode.HIERARCHICAL)
        crew = Crew(
            manager=None,
            workers=[mock_worker],
            config=config,
        )

        result = await crew.execute("Test fallback")

        # 无 Manager 时 fallback 到 Parallel，直接返回 Worker 输出
        assert len(result.worker_results) == 1
        assert result.worker_results[0].output == "Result from worker"

    @pytest.mark.asyncio
    async def test_crew_shared_context_disabled(self, mock_manager):
        """关闭共享上下文时，Worker 不应收到 shared_context."""
        worker = MagicMock()
        worker.config = AgentConfig(name="worker")
        worker.execute = AsyncMock(
            return_value=MagicMock(
                output="Result",
                reasoning="",
                tool_calls=[],
                status="success",
            )
        )

        config = CrewConfig(mode=CrewMode.PARALLEL, shared_context_enabled=False)
        crew = Crew(
            manager=mock_manager,
            workers=[worker],
            config=config,
        )

        await crew.execute("Test no shared context")

        # Worker 的 context 中不应包含 shared_context
        call_args = worker.execute.call_args
        context_arg = call_args[1]["context"]
        assert "shared_context" not in context_arg


# ---------------------------------------------------------------------------
# Phase 10: Sequential Task Building
# ---------------------------------------------------------------------------

class TestCrewSequentialTask:
    """测试 Sequential 模式任务构建."""

    def test_build_sequential_task_with_previous_outputs(self):
        """_build_sequential_task 应包含前一个 Worker 的输出."""
        crew = Crew()
        previous = [
            CrewWorkerResult(
                worker_name="worker_a",
                task=CrewTask(description="Task A"),
                output="Output from A",
                success=True,
            ),
        ]

        task_desc = crew._build_sequential_task(
            "Original task",
            "worker_b",
            previous,
        )

        assert "Original task" in task_desc
        assert "worker_a" in task_desc
        assert "Output from A" in task_desc

    def test_build_sequential_task_with_errors(self):
        """_build_sequential_task 应包含前一个 Worker 的错误信息."""
        crew = Crew()
        previous = [
            CrewWorkerResult(
                worker_name="worker_a",
                task=CrewTask(description="Task A"),
                success=False,
                error="Something went wrong",
            ),
        ]

        task_desc = crew._build_sequential_task(
            "Original task",
            "worker_b",
            previous,
        )

        assert "ERROR: Something went wrong" in task_desc


# ---------------------------------------------------------------------------
# Phase 10: Shared Context Trimming
# ---------------------------------------------------------------------------

class TestCrewSharedContextTrimming:
    """测试共享上下文大小限制."""

    def test_trim_shared_context_when_too_large(self):
        """shared_context 超过大小时应被截断."""
        config = CrewConfig(max_shared_context_size=100)
        crew = Crew(config=config)

        # 构造一个很大的 shared_context
        crew.shared_context["worker_outputs"] = {
            "worker_1": {"output": "x" * 10000, "success": True, "error": ""},
        }

        crew._trim_shared_context()

        # 输出应被截断
        output = crew.shared_context["worker_outputs"]["worker_1"]["output"]
        assert len(output) < 10000
        assert "truncated" in output


# ---------------------------------------------------------------------------
# Phase 10: CrewNodeExecutor
# ---------------------------------------------------------------------------

class TestCrewNodeExecutor:
    """测试 CrewNodeExecutor Workflow 集成."""

    def test_crew_node_executor_missing_crew_id(self):
        """缺少 crew_id 时应返回失败."""
        import asyncio
        from nexus.engine.node_executors import CrewNodeExecutor
        from nexus.engine.workflow_engine import Node, NodeResult
        from nexus.engine.enums import NodeType, NodeStatus
        from nexus.engine.state_manager import WorkflowState

        executor = CrewNodeExecutor()
        node = Node(id="crew_1", type=NodeType.CREW, config={"task_description": "test"})
        state = WorkflowState(
            run_id="r1",
            workflow_id="wf1",
            version=1,
            status=MagicMock(),
            node_states={},
            env_vars={},
            run_vars={},
            node_outputs={},
            trigger_payload={},
        )

        result = asyncio.run(executor.execute(node, {}, state, "r1"))

        assert result.status == NodeStatus.FAILED
        assert "crew_id not specified" in result.error["message"]

    def test_crew_node_executor_missing_task_description(self):
        """缺少 task_description 时应返回失败."""
        import asyncio
        from nexus.engine.node_executors import CrewNodeExecutor
        from nexus.engine.workflow_engine import Node
        from nexus.engine.enums import NodeType, NodeStatus
        from nexus.engine.state_manager import WorkflowState

        executor = CrewNodeExecutor()
        node = Node(id="crew_1", type=NodeType.CREW, config={"crew_id": "some-id"})
        state = WorkflowState(
            run_id="r1",
            workflow_id="wf1",
            version=1,
            status=MagicMock(),
            node_states={},
            env_vars={},
            run_vars={},
            node_outputs={},
            trigger_payload={},
        )

        result = asyncio.run(executor.execute(node, {}, state, "r1"))

        assert result.status == NodeStatus.FAILED
        assert "task_description not specified" in result.error["message"]


# ---------------------------------------------------------------------------
# Phase 10: Crew Mode Enum
# ---------------------------------------------------------------------------

class TestCrewMode:
    """测试 CrewMode Enum."""

    def test_crew_mode_values(self):
        """CrewMode 应包含三种模式."""
        assert CrewMode.HIERARCHICAL.value == "hierarchical"
        assert CrewMode.SEQUENTIAL.value == "sequential"
        assert CrewMode.PARALLEL.value == "parallel"

    def test_crew_mode_from_string(self):
        """应能从字符串创建 CrewMode."""
        assert CrewMode("hierarchical") == CrewMode.HIERARCHICAL
        assert CrewMode("sequential") == CrewMode.SEQUENTIAL
        assert CrewMode("parallel") == CrewMode.PARALLEL

"""WorkflowEngine单元测试.

覆盖:
- WorkflowDefinition验证（循环依赖、边界节点、非法边）
- WorkflowEngine执行流程（线性、分支、并行）
- 节点执行器注册与分派
- 超时与步数限制
- 状态合并与错误处理
- 边界节点自动注入
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.engine.enums import NodeStatus, NodeType, RunStatus
from nexus.engine.state_manager import WorkflowState
from nexus.engine.workflow_engine import (
    Edge,
    Node,
    NodeResult,
    RunResult,
    WorkflowDefinition,
    WorkflowEngine,
)
from nexus.exceptions import (
    CircularDependencyException,
    WorkflowExecutionException,
    WorkflowValidationException,
)
from tests.conftest import MockNodeExecutor


class TestWorkflowDefinition:
    """测试工作流定义验证."""

    def test_simple_linear_workflow_valid(self):
        """简单线性工作流应通过验证."""
        wf = WorkflowDefinition(
            nodes=[
                Node(id="start", type=NodeType.START, config={}),
                Node(id="agent", type=NodeType.AGENT, config={}),
                Node(id="end", type=NodeType.END, config={}),
            ],
            edges=[
                Edge(source="start", target="agent"),
                Edge(source="agent", target="end"),
            ],
        )
        wf.validate()  # 不应抛出异常
        assert len(wf.nodes) == 3

    def test_circular_dependency_detection(self):
        """应检测到循环依赖并抛出异常."""
        wf = WorkflowDefinition(
            nodes=[
                Node(id="a", type=NodeType.AGENT, config={}, depends_on=["c"]),
                Node(id="b", type=NodeType.AGENT, config={}, depends_on=["a"]),
                Node(id="c", type=NodeType.AGENT, config={}, depends_on=["b"]),
            ],
            edges=[
                Edge(source="a", target="b"),
                Edge(source="b", target="c"),
                Edge(source="c", target="a"),
            ],
        )
        with pytest.raises(CircularDependencyException) as exc_info:
            wf.validate()
        assert "a" in str(exc_info.value)

    def test_multiple_start_nodes_rejected(self):
        """多个start节点应被拒绝."""
        wf = WorkflowDefinition(
            nodes=[
                Node(id="start1", type=NodeType.START, config={}),
                Node(id="start2", type=NodeType.START, config={}),
            ],
            edges=[],
        )
        with pytest.raises(WorkflowValidationException) as exc_info:
            wf.validate()
        assert "start node" in str(exc_info.value).lower()

    def test_multiple_end_nodes_rejected(self):
        """多个end节点应被拒绝."""
        wf = WorkflowDefinition(
            nodes=[
                Node(id="end1", type=NodeType.END, config={}),
                Node(id="end2", type=NodeType.END, config={}),
            ],
            edges=[],
        )
        with pytest.raises(WorkflowValidationException) as exc_info:
            wf.validate()
        assert "end node" in str(exc_info.value).lower()

    def test_unknown_node_in_edge_rejected(self):
        """边引用不存在的节点应被拒绝."""
        wf = WorkflowDefinition(
            nodes=[
                Node(id="start", type=NodeType.START, config={}),
            ],
            edges=[
                Edge(source="start", target="nonexistent"),
            ],
        )
        with pytest.raises(WorkflowValidationException) as exc_info:
            wf.validate()
        assert "nonexistent" in str(exc_info.value)

    def test_get_dependencies(self):
        """测试获取节点依赖."""
        wf = WorkflowDefinition(
            nodes=[
                Node(id="a", type=NodeType.AGENT, config={}, depends_on=["b"]),
                Node(id="b", type=NodeType.AGENT, config={}),
            ],
            edges=[],
        )
        assert wf.get_dependencies("a") == ["b"]
        assert wf.get_dependencies("b") == []

    def test_get_downstream(self):
        """测试获取下游节点."""
        wf = WorkflowDefinition(
            nodes=[
                Node(id="a", type=NodeType.AGENT, config={}),
                Node(id="b", type=NodeType.AGENT, config={}),
                Node(id="c", type=NodeType.AGENT, config={}),
            ],
            edges=[
                Edge(source="a", target="b"),
                Edge(source="a", target="c"),
            ],
        )
        downstream = wf.get_downstream("a")
        assert set(downstream) == {"b", "c"}

    def test_get_upstream(self):
        """测试获取上游节点."""
        wf = WorkflowDefinition(
            nodes=[
                Node(id="a", type=NodeType.AGENT, config={}),
                Node(id="b", type=NodeType.AGENT, config={}),
            ],
            edges=[
                Edge(source="a", target="b"),
            ],
        )
        assert wf.get_upstream("b") == ["a"]
        assert wf.get_upstream("a") == []


class TestWorkflowEngineExecution:
    """测试WorkflowEngine执行逻辑."""

    @pytest.mark.asyncio
    async def test_execute_linear_workflow(self, workflow_engine, simple_workflow):
        """线性工作流应正确执行并返回COMPLETED."""
        workflow_engine.register_executor(
            NodeType.START, MockNodeExecutor(output={"started": True})
        )
        workflow_engine.register_executor(
            NodeType.AGENT, MockNodeExecutor(output={"result": "agent_output"})
        )
        workflow_engine.register_executor(
            NodeType.END, MockNodeExecutor(output={"finished": True})
        )

        result = await workflow_engine.execute(
            workflow_def=simple_workflow,
            trigger_payload={"input": "test"},
            run_id="run-001",
        )

        assert isinstance(result, RunResult)
        assert result.run_id == "run-001"
        assert result.status == RunStatus.COMPLETED
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_execute_with_auto_injected_boundary_nodes(
        self, workflow_engine
    ):
        """未显式定义start/end时，应自动注入边界节点."""
        wf = WorkflowDefinition(
            nodes=[
                Node(id="agent_a", type=NodeType.AGENT, config={}),
            ],
            edges=[],
        )
        workflow_engine.register_executor(
            NodeType.START, MockNodeExecutor(output={})
        )
        workflow_engine.register_executor(
            NodeType.AGENT, MockNodeExecutor(output={"result": "ok"})
        )
        workflow_engine.register_executor(
            NodeType.END, MockNodeExecutor(output={})
        )

        result = await workflow_engine.execute(
            workflow_def=wf,
            trigger_payload={},
            run_id="run-002",
        )

        assert result.status == RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_parallel_execution(self, workflow_engine, parallel_workflow):
        """并行节点应同时执行."""
        execution_order = []

        class TrackingExecutor(MockNodeExecutor):
            async def execute(self, node, inputs, state, run_id):
                execution_order.append(node.id)
                await asyncio.sleep(0.05)  # 模拟耗时
                return NodeResult(
                    node_id=node.id,
                    status=NodeStatus.SUCCEEDED,
                    output={"node": node.id},
                )

        workflow_engine.register_executor(
            NodeType.START, MockNodeExecutor(output={})
        )
        workflow_engine.register_executor(
            NodeType.AGENT, TrackingExecutor(output={})
        )
        workflow_engine.register_executor(
            NodeType.END, MockNodeExecutor(output={})
        )

        result = await workflow_engine.execute(
            workflow_def=parallel_workflow,
            trigger_payload={},
            run_id="run-003",
        )

        assert result.status == RunStatus.COMPLETED
        # agent_a 和 agent_b 应在同一super-step中启动
        assert "agent_a" in execution_order
        assert "agent_b" in execution_order

    @pytest.mark.asyncio
    async def test_node_failure_propagation(self, workflow_engine, simple_workflow):
        """节点失败应导致工作流FAILED."""
        workflow_engine.register_executor(
            NodeType.START, MockNodeExecutor(output={})
        )
        workflow_engine.register_executor(
            NodeType.AGENT, MockNodeExecutor(fail=True)
        )
        workflow_engine.register_executor(
            NodeType.END, MockNodeExecutor(output={})
        )

        result = await workflow_engine.execute(
            workflow_def=simple_workflow,
            trigger_payload={},
            run_id="run-004",
        )

        assert result.status == RunStatus.FAILED

    @pytest.mark.asyncio
    async def test_missing_executor_returns_failed(self, workflow_engine, simple_workflow):
        """未注册执行器的节点应返回FAILED."""
        # 只注册START，不注册AGENT
        workflow_engine.register_executor(
            NodeType.START, MockNodeExecutor(output={})
        )

        result = await workflow_engine.execute(
            workflow_def=simple_workflow,
            trigger_payload={},
            run_id="run-005",
        )

        assert result.status == RunStatus.FAILED

    @pytest.mark.asyncio
    async def test_checkpoint_save_called(self, workflow_engine, simple_workflow, mock_checkpoint_mgr):
        """每步执行后应调用Checkpoint保存."""
        workflow_engine.register_executor(
            NodeType.START, MockNodeExecutor(output={})
        )
        workflow_engine.register_executor(
            NodeType.AGENT, MockNodeExecutor(output={"result": "ok"})
        )
        workflow_engine.register_executor(
            NodeType.END, MockNodeExecutor(output={})
        )

        await workflow_engine.execute(
            workflow_def=simple_workflow,
            trigger_payload={},
            run_id="run-006",
        )

        assert mock_checkpoint_mgr.save.called
        # 至少保存了 start, agent, end 三步
        assert mock_checkpoint_mgr.save.call_count >= 3

    @pytest.mark.asyncio
    async def test_event_bus_publish_called(self, workflow_engine, simple_workflow, mock_event_bus):
        """每步执行后应发布状态更新事件."""
        workflow_engine.register_executor(
            NodeType.START, MockNodeExecutor(output={})
        )
        workflow_engine.register_executor(
            NodeType.AGENT, MockNodeExecutor(output={"result": "ok"})
        )
        workflow_engine.register_executor(
            NodeType.END, MockNodeExecutor(output={})
        )

        await workflow_engine.execute(
            workflow_def=simple_workflow,
            trigger_payload={},
            run_id="run-007",
        )

        assert mock_event_bus.publish.called
        # 检查事件类型
        calls = mock_event_bus.publish.call_args_list
        assert any(
            call.args[0].get("type") == "run_state_update"
            for call in calls
        )

    @pytest.mark.asyncio
    async def test_pause_and_resume(self, workflow_engine, mock_state_manager):
        """测试暂停和恢复接口."""
        await workflow_engine.pause("run-008")
        mock_state_manager.update_status.assert_called_once()
        args = mock_state_manager.update_status.call_args
        assert args[0][1] == RunStatus.PAUSED

    @pytest.mark.asyncio
    async def test_cancel(self, workflow_engine, mock_state_manager):
        """测试取消接口."""
        await workflow_engine.cancel("run-009")
        mock_state_manager.update_status.assert_called_once()
        args = mock_state_manager.update_status.call_args
        assert args[0][1] == RunStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_retry_specific_node(self, workflow_engine, mock_checkpoint_mgr):
        """测试重试指定节点."""
        mock_state = MagicMock()
        mock_state.node_states = {"node_a": NodeStatus.FAILED}
        mock_checkpoint_mgr.load = AsyncMock(return_value=mock_state)

        await workflow_engine.retry("run-010", node_id="node_a")

        mock_checkpoint_mgr.load.assert_called_once_with("run-010")
        assert mock_state.node_states["node_a"] == NodeStatus.PENDING
        mock_checkpoint_mgr.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_all_failed_nodes(self, workflow_engine, mock_checkpoint_mgr):
        """测试重试所有失败节点."""
        mock_state = MagicMock()
        mock_state.node_states = {
            "node_a": NodeStatus.FAILED,
            "node_b": NodeStatus.SUCCEEDED,
            "node_c": NodeStatus.FAILED,
        }
        mock_checkpoint_mgr.load = AsyncMock(return_value=mock_state)

        await workflow_engine.retry("run-011")

        assert mock_state.node_states["node_a"] == NodeStatus.PENDING
        assert mock_state.node_states["node_b"] == NodeStatus.SUCCEEDED  # 不变
        assert mock_state.node_states["node_c"] == NodeStatus.PENDING


class TestWorkflowEngineInternals:
    """测试WorkflowEngine内部方法."""

    def test_auto_inject_start_node(self, workflow_engine):
        """测试自动注入start节点."""
        wf = WorkflowDefinition(
            nodes=[
                Node(id="agent_a", type=NodeType.AGENT, config={}),
            ],
            edges=[],
        )
        result = workflow_engine._auto_inject_boundary_nodes(wf)
        node_ids = {n.id for n in result.nodes}
        assert "__start__" in node_ids
        assert any(e.source == "__start__" for e in result.edges)

    def test_auto_inject_end_node(self, workflow_engine):
        """测试自动注入end节点."""
        wf = WorkflowDefinition(
            nodes=[
                Node(id="agent_a", type=NodeType.AGENT, config={}),
            ],
            edges=[],
        )
        result = workflow_engine._auto_inject_boundary_nodes(wf)
        node_ids = {n.id for n in result.nodes}
        assert "__end__" in node_ids
        assert any(e.target == "__end__" for e in result.edges)

    def test_no_duplicate_injection_when_explicit(self, workflow_engine):
        """显式定义start/end时不应重复注入."""
        wf = WorkflowDefinition(
            nodes=[
                Node(id="start", type=NodeType.START, config={}),
                Node(id="agent_a", type=NodeType.AGENT, config={}),
                Node(id="end", type=NodeType.END, config={}),
            ],
            edges=[
                Edge(source="start", target="agent_a"),
                Edge(source="agent_a", target="end"),
            ],
        )
        result = workflow_engine._auto_inject_boundary_nodes(wf)
        start_nodes = [n for n in result.nodes if n.type == NodeType.START]
        end_nodes = [n for n in result.nodes if n.type == NodeType.END]
        assert len(start_nodes) == 1
        assert len(end_nodes) == 1

    def test_is_terminal_all_succeeded(self, workflow_engine):
        """所有节点成功时应判定为终止状态."""
        state = WorkflowState(
            run_id="r1", workflow_id="w1", version=1, status=RunStatus.RUNNING
        )
        state.node_states = {
            "start": NodeStatus.SUCCEEDED,
            "agent": NodeStatus.SUCCEEDED,
            "end": NodeStatus.SUCCEEDED,
        }
        graph = {
            "start": Node(id="start", type=NodeType.START, config={}),
            "agent": Node(id="agent", type=NodeType.AGENT, config={}),
            "end": Node(id="end", type=NodeType.END, config={}),
        }
        assert workflow_engine._is_terminal(state, graph) is True

    def test_is_terminal_with_failed(self, workflow_engine):
        """有失败节点但所有节点已处理时应判定为终止."""
        state = WorkflowState(
            run_id="r1", workflow_id="w1", version=1, status=RunStatus.RUNNING
        )
        state.node_states = {
            "start": NodeStatus.SUCCEEDED,
            "agent": NodeStatus.FAILED,
            "end": NodeStatus.SKIPPED,
        }
        graph = {
            "start": Node(id="start", type=NodeType.START, config={}),
            "agent": Node(id="agent", type=NodeType.AGENT, config={}),
            "end": Node(id="end", type=NodeType.END, config={}),
        }
        assert workflow_engine._is_terminal(state, graph) is True

    def test_is_terminal_not_terminal(self, workflow_engine):
        """有PENDING节点时不应判定为终止."""
        state = WorkflowState(
            run_id="r1", workflow_id="w1", version=1, status=RunStatus.RUNNING
        )
        state.node_states = {
            "start": NodeStatus.SUCCEEDED,
            "agent": NodeStatus.PENDING,
        }
        graph = {
            "start": Node(id="start", type=NodeType.START, config={}),
            "agent": Node(id="agent", type=NodeType.AGENT, config={}),
        }
        assert workflow_engine._is_terminal(state, graph) is False

    def test_get_ready_nodes(self, workflow_engine):
        """测试获取就绪节点."""
        state = WorkflowState(
            run_id="r1", workflow_id="w1", version=1, status=RunStatus.RUNNING
        )
        state.node_states = {
            "start": NodeStatus.SUCCEEDED,
            "agent_a": NodeStatus.PENDING,
            "agent_b": NodeStatus.PENDING,
        }
        graph = {
            "start": Node(id="start", type=NodeType.START, config={}),
            "agent_a": Node(
                id="agent_a", type=NodeType.AGENT, config={}, depends_on=["start"]
            ),
            "agent_b": Node(
                id="agent_b", type=NodeType.AGENT, config={}, depends_on=["start"]
            ),
        }
        ready = workflow_engine._get_ready_nodes(graph, state)
        assert len(ready) == 2
        assert {n.id for n in ready} == {"agent_a", "agent_b"}

    def test_get_ready_nodes_dependency_not_met(self, workflow_engine):
        """依赖未满足时不应标记为就绪."""
        state = WorkflowState(
            run_id="r1", workflow_id="w1", version=1, status=RunStatus.RUNNING
        )
        state.node_states = {
            "start": NodeStatus.PENDING,
            "agent": NodeStatus.PENDING,
        }
        graph = {
            "start": Node(id="start", type=NodeType.START, config={}),
            "agent": Node(
                id="agent", type=NodeType.AGENT, config={}, depends_on=["start"]
            ),
        }
        ready = workflow_engine._get_ready_nodes(graph, state)
        assert len(ready) == 0

    def test_merge_result_success(self, workflow_engine):
        """测试成功结果合并到状态."""
        state = WorkflowState(
            run_id="r1", workflow_id="w1", version=1, status=RunStatus.RUNNING
        )
        node = Node(id="agent", type=NodeType.AGENT, config={})
        result = NodeResult(
            node_id="agent", status=NodeStatus.SUCCEEDED, output={"key": "value"}
        )

        workflow_engine._merge_result(state, node, result)

        assert state.node_states["agent"] == NodeStatus.SUCCEEDED
        assert state.node_outputs["agent"] == {"key": "value"}

    def test_merge_result_failure(self, workflow_engine):
        """测试失败结果合并到状态."""
        state = WorkflowState(
            run_id="r1", workflow_id="w1", version=1, status=RunStatus.RUNNING
        )
        node = Node(id="agent", type=NodeType.AGENT, config={})
        result = NodeResult(
            node_id="agent",
            status=NodeStatus.FAILED,
            error={"message": "oops"},
        )

        workflow_engine._merge_result(state, node, result)

        assert state.node_states["agent"] == NodeStatus.FAILED
        assert state.node_outputs["agent"] == {"error": {"message": "oops"}}

    def test_finalize_state_with_failure(self, workflow_engine):
        """有失败节点时最终状态应为FAILED."""
        state = WorkflowState(
            run_id="r1", workflow_id="w1", version=1, status=RunStatus.RUNNING
        )
        state.node_states = {
            "start": NodeStatus.SUCCEEDED,
            "agent": NodeStatus.FAILED,
        }
        graph = {
            "start": Node(id="start", type=NodeType.START, config={}),
            "agent": Node(id="agent", type=NodeType.AGENT, config={}),
        }
        workflow_engine._finalize_state(state, graph)
        assert state.status == RunStatus.FAILED

    def test_finalize_state_all_success(self, workflow_engine):
        """全部成功时最终状态应为COMPLETED."""
        state = WorkflowState(
            run_id="r1", workflow_id="w1", version=1, status=RunStatus.RUNNING
        )
        state.node_states = {
            "start": NodeStatus.SUCCEEDED,
            "agent": NodeStatus.SUCCEEDED,
        }
        state.node_outputs = {"agent": {"result": "ok"}}
        graph = {
            "start": Node(id="start", type=NodeType.START, config={}),
            "agent": Node(id="agent", type=NodeType.AGENT, config={}),
        }
        workflow_engine._finalize_state(state, graph)
        assert state.status == RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_handle_node_error(self, workflow_engine, mock_event_bus):
        """测试节点错误处理."""
        state = WorkflowState(
            run_id="r1", workflow_id="w1", version=1, status=RunStatus.RUNNING
        )
        node = Node(id="agent", type=NodeType.AGENT, config={})
        error = ValueError("something went wrong")

        await workflow_engine._handle_node_error(node, error, state)

        assert state.node_states["agent"] == NodeStatus.FAILED
        assert "something went wrong" in str(state.node_outputs["agent"]["error"]["message"])
        mock_event_bus.publish.assert_called_once()
        event = mock_event_bus.publish.call_args[0][0]
        assert event["type"] == "node_error"
        assert event["node_id"] == "agent"

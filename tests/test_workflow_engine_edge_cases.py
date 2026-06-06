"""工作流引擎边界条件测试.

修复 (S3-1): 重写之前 14 个红测试。
原版 bug:
- 11 个 TypeError: `WorkflowEngine()` 漏传 5 个依赖参数
- 3 个 AssertionError: 节点执行器未全部注册（缺 END/START/CONDITION）

现版策略:
- 复用 conftest.py 的 `workflow_engine` fixture（5 个依赖齐全）
- 复用 `MockNodeExecutor` 或在 test 中注册需要的所有 executor
- 删除与 test_workflow_engine.py 重复的部分，专注于真正"边界"的场景

覆盖:
- 循环依赖检测 (4 tests) — 保留
- 空工作流 / 最小工作流 (2 tests) — 修复
- 深度依赖链 (1 test) — 修复（带 fixture）
- 大量并行 (1 test) — 修复
- 状态合并 (3 tests) — 修复
- 错误处理 (2 tests) — 修复
"""

import asyncio

import pytest

from nexus.engine.enums import NodeStatus, NodeType, RunStatus
from nexus.engine.state_manager import WorkflowState
from nexus.engine.workflow_engine import (
    Edge,
    Node,
    NodeExecutor,
    NodeResult,
    WorkflowDefinition,
    WorkflowEngine,
)
from nexus.exceptions import (
    CircularDependencyException,
    NexusException,
)


# ---------------------------------------------------------------------------
# 辅助 Executor
# ---------------------------------------------------------------------------


class _NoOpExecutor(NodeExecutor):
    """返回 SUCCEEDED + 空 output，可用于所有节点类型。"""

    async def execute(self, node, inputs, state, run_id):
        return NodeResult(
            node_id=node.id,
            status=NodeStatus.SUCCEEDED,
            output={"node_id": node.id},
        )


class _FailingExecutor(NodeExecutor):
    """总是抛异常的 executor，用于测错误传播。"""

    async def execute(self, node, inputs, state, run_id):
        raise ValueError(f"Intentional failure in {node.id}")


def _register_all_basic_executors(engine: WorkflowEngine) -> None:
    """注册 START/AGENT/END/CONDITION 4 个基本 executor，覆盖所有节点类型。"""
    for nt in (NodeType.START, NodeType.AGENT, NodeType.END, NodeType.CONDITION):
        engine.register_executor(nt, _NoOpExecutor())


# ---------------------------------------------------------------------------
# 循环依赖检测
# ---------------------------------------------------------------------------


class TestCircularDependencyEdgeCases:
    """测试循环依赖检测的边界情况."""

    def test_self_loop_detection(self):
        """自环应被检测为循环依赖."""
        wf = WorkflowDefinition(
            nodes=[
                Node(id="a", type=NodeType.AGENT, config={}, depends_on=["a"]),
            ],
            edges=[Edge(source="a", target="a")],
        )

        with pytest.raises(CircularDependencyException):
            wf.validate()

    def test_two_node_cycle(self):
        """两节点循环应被检测."""
        wf = WorkflowDefinition(
            nodes=[
                Node(id="a", type=NodeType.AGENT, config={}, depends_on=["b"]),
                Node(id="b", type=NodeType.AGENT, config={}, depends_on=["a"]),
            ],
            edges=[Edge(source="a", target="b"), Edge(source="b", target="a")],
        )

        with pytest.raises(CircularDependencyException):
            wf.validate()

    def test_large_cycle_detection(self):
        """大循环（10节点）应被检测."""
        num_nodes = 10
        nodes = [
            Node(
                id=f"node_{i}",
                type=NodeType.AGENT,
                config={},
                depends_on=[f"node_{(i + 1) % num_nodes}"],
            )
            for i in range(num_nodes)
        ]
        wf = WorkflowDefinition(nodes=nodes, edges=[])

        with pytest.raises(CircularDependencyException):
            wf.validate()

    def test_cycle_with_extra_nodes(self):
        """包含额外非循环节点的循环应被检测."""
        wf = WorkflowDefinition(
            nodes=[
                Node(id="a", type=NodeType.AGENT, config={}, depends_on=["c"]),
                Node(id="b", type=NodeType.AGENT, config={}, depends_on=["a"]),
                Node(id="c", type=NodeType.AGENT, config={}, depends_on=["b"]),
                Node(id="d", type=NodeType.AGENT, config={}),
            ],
            edges=[
                Edge(source="a", target="b"),
                Edge(source="b", target="c"),
                Edge(source="c", target="a"),
            ],
        )

        with pytest.raises(CircularDependencyException):
            wf.validate()


# ---------------------------------------------------------------------------
# 最小/边界工作流
# ---------------------------------------------------------------------------


class TestMinimalWorkflows:
    """最小/边界工作流的真实执行。"""

    @pytest.mark.asyncio
    async def test_empty_workflow_auto_injected_and_completes(self, workflow_engine):
        """空工作流应自动注入 start/end 并完成."""
        _register_all_basic_executors(workflow_engine)
        wf = WorkflowDefinition(nodes=[], edges=[])

        result = await workflow_engine.execute(
            workflow_def=wf,
            trigger_payload={},
            run_id="run-empty",
        )

        assert result.status == RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_single_agent_workflow(self, workflow_engine):
        """单 AGENT 节点工作流（start/end 自动注入）应完成."""
        _register_all_basic_executors(workflow_engine)
        wf = WorkflowDefinition(
            nodes=[Node(id="only", type=NodeType.AGENT, config={})],
            edges=[],
        )

        result = await workflow_engine.execute(
            workflow_def=wf,
            trigger_payload={},
            run_id="run-single",
        )

        assert result.status == RunStatus.COMPLETED


# ---------------------------------------------------------------------------
# 深度依赖链
# ---------------------------------------------------------------------------


class TestDeepDependencyChain:
    """深度依赖链执行."""

    @pytest.mark.asyncio
    async def test_chain_of_50_nodes_completes(self, workflow_engine):
        """50 节点线性链应能正确执行并 COMPLETED."""
        _register_all_basic_executors(workflow_engine)

        num_nodes = 50
        nodes = []
        edges = []
        for i in range(num_nodes):
            nt = NodeType.START if i == 0 else (NodeType.END if i == num_nodes - 1 else NodeType.AGENT)
            nodes.append(Node(id=f"n_{i}", type=nt, config={}))
            if i > 0:
                edges.append(Edge(source=f"n_{i - 1}", target=f"n_{i}"))

        wf = WorkflowDefinition(nodes=nodes, edges=edges)
        wf.validate()  # 不应抛

        result = await workflow_engine.execute(
            workflow_def=wf,
            trigger_payload={},
            run_id="run-deep",
        )

        assert result.status == RunStatus.COMPLETED


# ---------------------------------------------------------------------------
# 大量并行
# ---------------------------------------------------------------------------


class TestParallelExecution:
    """并行执行的真实行为."""

    @pytest.mark.asyncio
    async def test_many_parallel_branches_completes(self, workflow_engine):
        """20 个并行分支应能 COMPLETED."""
        _register_all_basic_executors(workflow_engine)

        n = 20
        nodes = [Node(id="start", type=NodeType.START, config={})]
        for i in range(n):
            nodes.append(Node(id=f"p_{i}", type=NodeType.AGENT, config={}))
        nodes.append(Node(id="end", type=NodeType.END, config={}))

        edges = [Edge(source="start", target=f"p_{i}") for i in range(n)]
        edges += [Edge(source=f"p_{i}", target="end") for i in range(n)]

        wf = WorkflowDefinition(nodes=nodes, edges=edges)

        result = await workflow_engine.execute(
            workflow_def=wf,
            trigger_payload={},
            run_id="run-parallel",
        )

        assert result.status == RunStatus.COMPLETED


# ---------------------------------------------------------------------------
# 状态合并
# ---------------------------------------------------------------------------


class TestStateMerge:
    """_merge_result 真实行为."""

    def test_merge_large_output(self, workflow_engine):
        """合并 100KB 大输出."""
        state = WorkflowState(
            run_id="r1", workflow_id="w1", version=1, status=RunStatus.RUNNING
        )
        large_output = {"data": "x" * 100_000}
        node = Node(id="big", type=NodeType.AGENT, config={})
        result = NodeResult(
            node_id="big",
            status=NodeStatus.SUCCEEDED,
            output=large_output,
        )

        workflow_engine._merge_result(state, node, result)
        assert state.node_outputs["big"] == large_output

    def test_merge_nested_error_structure(self, workflow_engine):
        """合并嵌套错误结构到 node_outputs。"""
        state = WorkflowState(
            run_id="r1", workflow_id="w1", version=1, status=RunStatus.RUNNING
        )
        node = Node(id="agent", type=NodeType.AGENT, config={})
        error = {
            "message": "Error occurred",
            "details": {
                "code": 500,
                "stack": ["frame1", "frame2"],
                "context": {"key": "value"},
            },
        }
        result = NodeResult(
            node_id="agent",
            status=NodeStatus.FAILED,
            error=error,
        )

        workflow_engine._merge_result(state, node, result)
        assert state.node_states["agent"] == NodeStatus.FAILED
        assert "error" in state.node_outputs["agent"]

    def test_merge_multiple_node_outputs(self, workflow_engine):
        """合并 10 个不同节点的输出."""
        state = WorkflowState(
            run_id="r1", workflow_id="w1", version=1, status=RunStatus.RUNNING
        )
        for i in range(10):
            node = Node(id=f"node_{i}", type=NodeType.AGENT, config={})
            result = NodeResult(
                node_id=f"node_{i}",
                status=NodeStatus.SUCCEEDED,
                output={"index": i},
            )
            workflow_engine._merge_result(state, node, result)

        assert len(state.node_outputs) == 10
        assert len(state.node_states) == 10
        assert state.node_outputs["node_5"] == {"index": 5}


# ---------------------------------------------------------------------------
# 错误处理
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """_handle_node_error 与节点异常的传播。"""

    @pytest.mark.asyncio
    async def test_node_exception_becomes_failed_status(self, workflow_engine):
        """节点执行器抛异常 → 该节点 FAILED，整个 run FAILED."""
        for nt in (NodeType.START, NodeType.AGENT, NodeType.END):
            workflow_engine.register_executor(nt, _FailingExecutor())

        wf = WorkflowDefinition(
            nodes=[
                Node(id="start", type=NodeType.START, config={}),
                Node(id="failing", type=NodeType.AGENT, config={}),
                Node(id="end", type=NodeType.END, config={}),
            ],
            edges=[
                Edge(source="start", target="failing"),
                Edge(source="failing", target="end"),
            ],
        )

        result = await workflow_engine.execute(
            workflow_def=wf,
            trigger_payload={},
            run_id="run-fail",
        )

        assert result.status == RunStatus.FAILED

    def test_handle_node_error_records_error(self, workflow_engine):
        """_handle_node_error 把异常信息写到 node_states + node_outputs。"""
        state = WorkflowState(
            run_id="r1", workflow_id="w1", version=1, status=RunStatus.RUNNING
        )
        node = Node(id="agent", type=NodeType.AGENT, config={})

        # 自定义异常类型
        class CustomError(NexusException):
            def __init__(self, code, message):
                # 不传 error_code 走默认 INTERNAL_SERVER_ERROR
                super().__init__(message=message)
                self.code = code

        error = CustomError(500, "Custom error occurred")

        # 同步调用 _handle_node_error
        asyncio.run(workflow_engine._handle_node_error(node, error, state))

        assert state.node_states["agent"] == NodeStatus.FAILED
        assert "error" in state.node_outputs["agent"]
        assert "Custom error occurred" in str(state.node_outputs["agent"]["error"])

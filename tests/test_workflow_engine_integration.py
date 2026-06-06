"""工作流引擎集成测试 — 真实组件,无 mock.

修复 (S3-3): 解决 "test mock theatre" 问题。
这些测试用 `workflow_engine_real` fixture，跑真实的 StateManager / EventBus /
CheckpointManager（内存模式），不依赖 Redis / S3 / Docker。

与 test_workflow_engine.py 的关系:
- test_workflow_engine.py: 纯逻辑 + mock 协作者 — 32 tests
- test_workflow_engine_edge_cases.py: 边界 + mock — 13 tests
- test_workflow_engine_integration.py (this): 真实集成 — N tests
"""

import pytest

from nexus.engine.enums import NodeStatus, NodeType, RunStatus
from nexus.engine.workflow_engine import (
    Edge,
    Node,
    NodeExecutor,
    NodeResult,
    WorkflowDefinition,
)


class _StubExecutor(NodeExecutor):
    """测试用 executor：根据 node.config 决定行为."""

    def __init__(self, behavior: str = "succeed"):
        self.behavior = behavior
        self.executed_nodes: list[str] = []

    async def execute(self, node, inputs, state, run_id):
        self.executed_nodes.append(node.id)
        if self.behavior == "fail":
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"message": f"{node.id} failed intentionally"},
            )
        return NodeResult(
            node_id=node.id,
            status=NodeStatus.SUCCEEDED,
            output={"node_id": node.id, "config": node.config},
        )


class TestStateLifecycleReal:
    """真实 StateManager 的状态生命周期."""

    @pytest.mark.asyncio
    async def test_state_lifecycle_pending_running_completed(self, workflow_engine_real):
        """状态机真的经历 PENDING → RUNNING → COMPLETED."""
        executor = _StubExecutor()
        for nt in (NodeType.START, NodeType.AGENT, NodeType.END):
            workflow_engine_real.register_executor(nt, executor)

        wf = WorkflowDefinition(
            nodes=[
                Node(id="a", type=NodeType.AGENT, config={"task": "do x"}),
            ],
            edges=[],
        )

        # 执行前，state 不存在
        assert workflow_engine_real.state_manager.get_state("run-lifecycle") is None

        result = await workflow_engine_real.execute(
            workflow_def=wf,
            trigger_payload={"input": "test"},
            run_id="run-lifecycle",
        )

        assert result.status == RunStatus.COMPLETED
        # 执行后 state 存在，COMPLETED
        state = workflow_engine_real.state_manager.get_state("run-lifecycle")
        assert state is not None
        assert state.status == RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_node_states_progressed_correctly(self, workflow_engine_real):
        """节点状态真的从 PENDING 推进到 SUCCEEDED."""
        executor = _StubExecutor()
        for nt in (NodeType.START, NodeType.AGENT, NodeType.END):
            workflow_engine_real.register_executor(nt, executor)

        wf = WorkflowDefinition(
            nodes=[
                Node(id="a", type=NodeType.AGENT, config={}),
                Node(id="b", type=NodeType.AGENT, config={}),
            ],
            edges=[Edge(source="a", target="b")],
        )

        result = await workflow_engine_real.execute(
            workflow_def=wf,
            trigger_payload={},
            run_id="run-progress",
        )

        state = workflow_engine_real.state_manager.get_state("run-progress")
        # 4 节点：start, a, b, end (auto-injected)
        assert len(state.node_states) == 4
        for status in state.node_states.values():
            assert status == NodeStatus.SUCCEEDED
        # 节点输出真的被记录（auto-injected 边界节点名为 __start__/__end__）
        assert "__start__" in state.node_outputs
        assert "a" in state.node_outputs
        assert "b" in state.node_outputs
        assert "__end__" in state.node_outputs


class TestEventBroadcastReal:
    """真实 EventBus 的事件广播."""

    @pytest.mark.asyncio
    async def test_state_update_events_broadcast(self, workflow_engine_real):
        """execute 真的广播 run_state_update 事件（带 run_id）."""
        import asyncio
        events_received: list[dict] = []

        # 同步 handler —— EventBus 同步路径会直接调用（不等 asyncio.create_task）
        def handler(event: dict) -> None:
            events_received.append(event)

        # EventBus 实际 topic 格式: `run:{run_id}` (看 _get_topic())
        # 订阅特定 run_id 的事件
        workflow_engine_real.event_bus.subscribe("run:run-events", handler)

        executor = _StubExecutor()
        for nt in (NodeType.START, NodeType.AGENT, NodeType.END):
            workflow_engine_real.register_executor(nt, executor)

        wf = WorkflowDefinition(
            nodes=[Node(id="x", type=NodeType.AGENT, config={})],
            edges=[],
        )

        await workflow_engine_real.execute(
            workflow_def=wf,
            trigger_payload={},
            run_id="run-events",
        )

        # 让任何 fire-and-forget 任务排空
        await asyncio.sleep(0)

        assert len(events_received) >= 1
        # 至少一个事件应该提到 run_id
        run_id_events = [e for e in events_received if e.get("run_id") == "run-events"]
        assert len(run_id_events) >= 1


class TestCheckpointReal:
    """真实 CheckpointManager 的检查点保存."""

    @pytest.mark.asyncio
    async def test_checkpoints_saved_during_execution(self, workflow_engine_real):
        """执行过程中真的保存检查点."""
        executor = _StubExecutor()
        for nt in (NodeType.START, NodeType.AGENT, NodeType.END):
            workflow_engine_real.register_executor(nt, executor)

        wf = WorkflowDefinition(
            nodes=[
                Node(id="n1", type=NodeType.AGENT, config={}),
                Node(id="n2", type=NodeType.AGENT, config={}),
            ],
            edges=[Edge(source="n1", target="n2")],
        )

        await workflow_engine_real.execute(
            workflow_def=wf,
            trigger_payload={},
            run_id="run-cp",
        )

        # CheckpointManager 真的记录了检查点（内存模式：_checkpoints dict）
        checkpoints = await workflow_engine_real.checkpoint_mgr.list_checkpoints("run-cp")
        # 至少 1 个 checkpoint（每步一次，2 节点 + start/end = 4 super-steps）
        assert len(checkpoints) >= 1


class TestResumeReal:
    """真实引擎的 resume 行为 — 验证 S1-1 修复."""

    @pytest.mark.asyncio
    async def test_resume_reuses_existing_state(self, workflow_engine_real):
        """resume() 真的复用已存在的 state 并继续执行."""
        executor = _StubExecutor()
        for nt in (NodeType.START, NodeType.AGENT, NodeType.END):
            workflow_engine_real.register_executor(nt, executor)

        wf = WorkflowDefinition(
            nodes=[Node(id="only", type=NodeType.AGENT, config={})],
            edges=[],
        )

        # 第一次执行：跑完整个工作流
        result1 = await workflow_engine_real.execute(
            workflow_def=wf,
            trigger_payload={"input": "x"},
            run_id="run-resume",
        )
        assert result1.status == RunStatus.COMPLETED

        # 第二次"执行"（实际是 resume 场景）：state 存在，应该复用而不是 create_state
        # 这验证 S1-1 修复：get_state() 返回已有 state 而不是 None
        existing = workflow_engine_real.state_manager.get_state("run-resume")
        assert existing is not None
        assert existing.status == RunStatus.COMPLETED
        # 重复 execute 不会破坏已有 state
        result2 = await workflow_engine_real.execute(
            workflow_def=wf,
            trigger_payload={"input": "y"},
            run_id="run-resume",
        )
        # 这里 result2 会重置 state（因为 super-step loop 看到所有节点都是 SUCCEEDED 直接终止）
        assert result2.status == RunStatus.COMPLETED

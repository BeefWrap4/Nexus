"""工作流性能基准测试.

测试不同复杂度的工作流执行性能，验证是否满足SLO要求。
"""

import asyncio
import time
from typing import Any, Dict

import pytest

from nexus.observability.slo import SLO
from nexus.engine.checkpoint import CheckpointManager
from nexus.engine.enums import NodeType
from nexus.engine.event_bus import EventBus
from nexus.engine.router_engine import RouterEngine
from nexus.engine.state_manager import StateManager
from nexus.engine.variable_pool import VariablePool
from nexus.engine.workflow_engine import WorkflowEngine
from nexus.engine.workflow_types import Edge, Node, WorkflowDefinition


def create_simple_workflow() -> WorkflowDefinition:
    """创建简单工作流(3节点).

    结构: start -> agent -> end
    """
    nodes = [
        Node(
            id="start",
            type=NodeType.START,
            config={"inputs": {}},
        ),
        Node(
            id="agent_node",
            type=NodeType.AGENT,
            config={
                "inputs": {"query": "{{trigger.query}}"},
                "agent_name": "test_agent",
            },
        ),
        Node(
            id="end",
            type=NodeType.END,
            config={"outputs": {"result": "{{agent_node.output}}"}},
        ),
    ]

    edges = [
        Edge(source="start", target="agent_node"),
        Edge(source="agent_node", target="end"),
    ]

    return WorkflowDefinition(
        nodes=nodes,
        edges=edges,
    )


def create_medium_workflow() -> WorkflowDefinition:
    """创建中等工作流(10节点).

    结构: start -> [agent1, agent2, agent3] -> [tool1, tool2] -> [agent4, agent5] -> condition -> end
    """
    nodes = [
        Node(id="start", type=NodeType.START, config={"inputs": {}}),
        Node(
            id="agent1",
            type=NodeType.AGENT,
            config={"inputs": {"query": "{{trigger.query}}"}, "agent_name": "agent1"},
        ),
        Node(
            id="agent2",
            type=NodeType.AGENT,
            config={"inputs": {"context": "{{agent1.output}}"}, "agent_name": "agent2"},
        ),
        Node(
            id="agent3",
            type=NodeType.AGENT,
            config={"inputs": {"context": "{{agent1.output}}"}, "agent_name": "agent3"},
        ),
        Node(
            id="tool1",
            type=NodeType.TOOL,
            config={"inputs": {"data": "{{agent2.output}}"}, "tool_name": "tool1"},
        ),
        Node(
            id="tool2",
            type=NodeType.TOOL,
            config={"inputs": {"data": "{{agent3.output}}"}, "tool_name": "tool2"},
        ),
        Node(
            id="agent4",
            type=NodeType.AGENT,
            config={"inputs": {"results": "{{tool1.output}}"}, "agent_name": "agent4"},
        ),
        Node(
            id="agent5",
            type=NodeType.AGENT,
            config={"inputs": {"results": "{{tool2.output}}"}, "agent_name": "agent5"},
        ),
        Node(
            id="condition",
            type=NodeType.CONDITION,
            config={
                "inputs": {
                    "result1": "{{agent4.output}}",
                    "result2": "{{agent5.output}}",
                },
                "condition": "{{result1.confidence > result2.confidence}}",
            },
        ),
        Node(
            id="end",
            type=NodeType.END,
            config={"outputs": {"final_result": "{{condition.output}}"}},
        ),
    ]

    edges = [
        Edge(source="start", target="agent1"),
        Edge(source="agent1", target="agent2"),
        Edge(source="agent1", target="agent3"),
        Edge(source="agent2", target="tool1"),
        Edge(source="agent3", target="tool2"),
        Edge(source="tool1", target="agent4"),
        Edge(source="tool2", target="agent5"),
        Edge(source="agent4", target="condition"),
        Edge(source="agent5", target="condition"),
        Edge(source="condition", target="end"),
    ]

    return WorkflowDefinition(
        nodes=nodes,
        edges=edges,
    )


def create_complex_workflow() -> WorkflowDefinition:
    """创建复杂工作流(20节点+并行).

    包含多个并行分支、条件判断和循环结构。
    """
    nodes = [
        Node(id="start", type=NodeType.START, config={"inputs": {}}),
        # 第一层：3个并行agent
        *[
            Node(
                id=f"agent_init_{i}",
                type=NodeType.AGENT,
                config={
                    "inputs": {"query": "{{trigger.query}}"},
                    "agent_name": f"init_agent_{i}",
                },
            )
            for i in range(3)
        ],
        # 第二层：4个并行tool
        *[
            Node(
                id=f"tool_process_{i}",
                type=NodeType.TOOL,
                config={
                    "inputs": {"data": f"{{{{agent_init_{i % 3}.output}}}}"},
                    "tool_name": f"process_tool_{i}",
                },
            )
            for i in range(4)
        ],
        # 第三层：5个并行agent进行深度分析
        *[
            Node(
                id=f"agent_analyze_{i}",
                type=NodeType.AGENT,
                config={
                    "inputs": {"data": f"{{{{tool_process_{i % 4}.output}}}}"},
                    "agent_name": f"analyze_agent_{i}",
                },
            )
            for i in range(5)
        ],
        # 第四层：聚合节点
        Node(
            id="aggregator",
            type=NodeType.AGENT,
            config={
                "inputs": {
                    f"analysis_{i}": f"{{{{agent_analyze_{i}.output}}}}"
                    for i in range(5)
                },
                "agent_name": "aggregator_agent",
            },
        ),
        # 第五层：条件分支
        Node(
            id="condition",
            type=NodeType.CONDITION,
            config={
                "inputs": {"aggregated": "{{aggregator.output}}"},
                "condition": "{{aggregated.confidence > 0.8}}",
            },
        ),
        # 第六层：高置信度路径
        Node(
            id="agent_finalize_high",
            type=NodeType.AGENT,
            config={
                "inputs": {"data": "{{aggregator.output}}"},
                "agent_name": "finalize_high_agent",
            },
        ),
        # 第七层：低置信度路径
        Node(
            id="agent_finalize_low",
            type=NodeType.AGENT,
            config={
                "inputs": {"data": "{{aggregator.output}}"},
                "agent_name": "finalize_low_agent",
            },
        ),
        # 第八层：最终输出
        Node(
            id="end",
            type=NodeType.END,
            config={"outputs": {"result": "{{condition.output}}"}},
        ),
    ]

    edges = [
        # start -> 第一层
        *[Edge(source="start", target=f"agent_init_{i}") for i in range(3)],
        # 第一层 -> 第二层
        *[
            Edge(source=f"agent_init_{i % 3}", target=f"tool_process_{i}")
            for i in range(4)
        ],
        # 第二层 -> 第三层
        *[
            Edge(source=f"tool_process_{i % 4}", target=f"agent_analyze_{i}")
            for i in range(5)
        ],
        # 第三层 -> aggregator
        *[Edge(source=f"agent_analyze_{i}", target="aggregator") for i in range(5)],
        # aggregator -> condition
        Edge(source="aggregator", target="condition"),
        # condition -> 两个分支
        Edge(source="condition", target="agent_finalize_high"),
        Edge(source="condition", target="agent_finalize_low"),
        # 两个分支 -> end
        Edge(source="agent_finalize_high", target="end"),
        Edge(source="agent_finalize_low", target="end"),
    ]

    return WorkflowDefinition(
        nodes=nodes,
        edges=edges,
    )


class MockNodeExecutor:
    """模拟节点执行器，用于性能测试."""

    async def execute(self, node: Node, inputs: Dict[str, Any], state: Any, run_id: str):
        """模拟执行，添加少量延迟以模拟真实场景."""
        from nexus.engine.enums import NodeStatus
        from nexus.engine.workflow_types import NodeResult

        # 模拟不同类型的延迟
        if node.type == NodeType.AGENT:
            await asyncio.sleep(0.1)  # Agent决策延迟
            output = {"answer": f"Result from {node.id}", "confidence": 0.9}
        elif node.type == NodeType.TOOL:
            await asyncio.sleep(0.05)  # 工具执行延迟
            output = {"data": f"Tool result from {node.id}"}
        elif node.type == NodeType.CONDITION:
            await asyncio.sleep(0.01)  # 条件判断延迟
            output = {"branch": "high_confidence"}
        else:
            await asyncio.sleep(0.001)  # 其他节点延迟
            output = {}

        return NodeResult(
            node_id=node.id,
            status=NodeStatus.SUCCEEDED,
            output=output,
        )


@pytest.fixture
async def workflow_engine():
    """创建工作流引擎fixture."""
    state_manager = StateManager()
    event_bus = EventBus()
    checkpoint_mgr = CheckpointManager()
    variable_pool = VariablePool()
    router_engine = RouterEngine()

    engine = WorkflowEngine(
        state_manager=state_manager,
        event_bus=event_bus,
        checkpoint_mgr=checkpoint_mgr,
        variable_pool=variable_pool,
        router_engine=router_engine,
    )

    # 注册mock执行器
    mock_executor = MockNodeExecutor()
    for node_type in NodeType:
        engine.register_executor(node_type, mock_executor)

    return engine


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_simple_workflow_performance(workflow_engine):
    """测试简单工作流(3节点)执行性能.

    SLO要求: p95 < 5秒
    """
    workflow = create_simple_workflow()
    trigger_payload = {"query": "test query"}
    run_id = "benchmark_simple_001"

    start_time = time.time()
    result = await workflow_engine.execute(workflow, trigger_payload, run_id)
    duration_ms = (time.time() - start_time) * 1000

    # 验证工作流成功完成
    assert result.status.value == "completed" or result.status == "completed"

    # 验证性能要求
    assert duration_ms < SLO.WORKFLOW_SIMPLE_P95_MS, (
        f"简单工作流执行时间 {duration_ms:.2f}ms 超过SLO阈值 {SLO.WORKFLOW_SIMPLE_P95_MS}ms"
    )

    print(f"✓ 简单工作流性能测试通过: {duration_ms:.2f}ms < {SLO.WORKFLOW_SIMPLE_P95_MS}ms")


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_medium_workflow_performance(workflow_engine):
    """测试中等工作流(10节点)执行性能.

    SLO要求: p95 < 15秒
    """
    workflow = create_medium_workflow()
    trigger_payload = {"query": "test query for medium workflow"}
    run_id = "benchmark_medium_001"

    start_time = time.time()
    result = await workflow_engine.execute(workflow, trigger_payload, run_id)
    duration_ms = (time.time() - start_time) * 1000

    # 验证工作流成功完成
    assert result.status.value == "completed" or result.status == "completed"

    # 验证性能要求
    assert duration_ms < SLO.WORKFLOW_MEDIUM_P95_MS, (
        f"中等工作流执行时间 {duration_ms:.2f}ms 超过SLO阈值 {SLO.WORKFLOW_MEDIUM_P95_MS}ms"
    )

    print(f"✓ 中等工作流性能测试通过: {duration_ms:.2f}ms < {SLO.WORKFLOW_MEDIUM_P95_MS}ms")


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_complex_workflow_performance(workflow_engine):
    """测试复杂工作流(20节点+并行)执行性能.

    SLO要求: p95 < 30秒
    """
    workflow = create_complex_workflow()
    trigger_payload = {"query": "test query for complex workflow"}
    run_id = "benchmark_complex_001"

    start_time = time.time()
    result = await workflow_engine.execute(workflow, trigger_payload, run_id)
    duration_ms = (time.time() - start_time) * 1000

    # 验证工作流成功完成
    assert result.status.value == "completed" or result.status == "completed"

    # 验证性能要求
    assert duration_ms < SLO.WORKFLOW_COMPLEX_P95_MS, (
        f"复杂工作流执行时间 {duration_ms:.2f}ms 超过SLO阈值 {SLO.WORKFLOW_COMPLEX_P95_MS}ms"
    )

    print(f"✓ 复杂工作流性能测试通过: {duration_ms:.2f}ms < {SLO.WORKFLOW_COMPLEX_P95_MS}ms")


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_workflow_concurrent_execution(workflow_engine):
    """测试并发工作流执行性能.

    验证系统能否处理多个并发工作流而不显著降低性能。
    """
    workflow = create_simple_workflow()
    num_concurrent = 5

    async def execute_workflow(idx: int):
        run_id = f"benchmark_concurrent_{idx}"
        trigger_payload = {"query": f"concurrent test {idx}"}
        start_time = time.time()
        result = await workflow_engine.execute(workflow, trigger_payload, run_id)
        duration_ms = (time.time() - start_time) * 1000
        return result, duration_ms

    # 并发执行多个工作流
    start_time = time.time()
    tasks = [execute_workflow(i) for i in range(num_concurrent)]
    results = await asyncio.gather(*tasks)
    total_duration_ms = (time.time() - start_time) * 1000

    # 验证所有工作流都成功完成
    for result, duration in results:
        assert result.status.value == "completed" or result.status == "completed"

    # 计算平均延迟
    avg_duration = sum(d for _, d in results) / len(results)

    # 验证并发性能：总时间应该远小于串行执行时间
    # 串行时间约为 avg_duration * num_concurrent
    # 并发时间应该接近 avg_duration（理想情况）
    speedup = (avg_duration * num_concurrent) / total_duration_ms

    print(f"✓ 并发工作流测试通过:")
    print(f"  - 并发数: {num_concurrent}")
    print(f"  - 平均单个工作流时间: {avg_duration:.2f}ms")
    print(f"  - 总执行时间: {total_duration_ms:.2f}ms")
    print(f"  - 加速比: {speedup:.2f}x")

    # 加速比应该大于1.5（表示有一定的并发优势）
    assert speedup > 1.5, f"并发加速比过低: {speedup:.2f}x"

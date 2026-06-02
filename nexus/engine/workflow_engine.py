"""DAG工作流执行引擎.

设计来源:
- WAT PhaseController: 阶段执行编排模式
- LangGraph StateGraph: 图状态机 + 增量更新
- Dify GraphEngine: 队列驱动并行执行
- Temporal: 确定性Workflow + 非确定性Activity分离

核心设计决策:
1. 图结构定义: 节点(Node) + 有向边(Edge)
2. 状态管理: 共享State对象 + 增量更新
3. 执行模型: Pregel-inspired Super-Step
4. 持久化: 每步Checkpoint到PostgreSQL
5. 并行: 独立节点自动并行执行
"""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from nexus.config import settings
from nexus.engine.checkpoint import CheckpointManager
from nexus.engine.enums import NodeStatus, NodeType, RunStatus
from nexus.engine.event_bus import EventBus
from nexus.engine.router_engine import RouterEngine
from nexus.engine.state_manager import StateManager, WorkflowState
from nexus.engine.variable_pool import VariablePool
from nexus.exceptions import WorkflowExecutionException


@dataclass
class Node:
    """工作流节点定义."""

    id: str
    type: NodeType
    config: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class Edge:
    """工作流边定义."""

    source: str
    target: str
    condition: Optional[str] = None  # 条件表达式


@dataclass
class WorkflowDefinition:
    """工作流定义."""

    nodes: list[Node]
    edges: list[Edge]

    def get_node(self, node_id: str) -> Optional[Node]:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def get_dependencies(self, node_id: str) -> list[str]:
        """获取节点的依赖（前置节点）."""
        node = self.get_node(node_id)
        return node.depends_on if node else []

    def get_downstream(self, node_id: str) -> list[str]:
        """获取下游节点."""
        return [e.target for e in self.edges if e.source == node_id]

    def get_upstream(self, node_id: str) -> list[str]:
        """获取上游节点."""
        return [e.source for e in self.edges if e.target == node_id]

    def validate(self) -> None:
        """验证工作流定义.

        Raises:
            CircularDependencyException: 存在循环依赖
            WorkflowValidationException: 其他验证错误
        """
        from nexus.exceptions import CircularDependencyException, WorkflowValidationException

        # 检查循环依赖
        visited = set()
        rec_stack = set()

        def has_cycle(node_id: str) -> bool:
            visited.add(node_id)
            rec_stack.add(node_id)
            for dep in self.get_dependencies(node_id):
                if dep not in visited:
                    if has_cycle(dep):
                        return True
                elif dep in rec_stack:
                    raise CircularDependencyException(list(rec_stack) + [dep])
            rec_stack.remove(node_id)
            return False

        for node in self.nodes:
            if node.id not in visited:
                has_cycle(node.id)

        # 检查必需节点
        node_ids = {n.id for n in self.nodes}
        for edge in self.edges:
            if edge.source not in node_ids:
                raise WorkflowValidationException(
                    f"Edge references unknown node: {edge.source}"
                )
            if edge.target not in node_ids:
                raise WorkflowValidationException(
                    f"Edge references unknown node: {edge.target}"
                )

        # 检查start/end节点
        start_nodes = [n for n in self.nodes if n.type == NodeType.START]
        end_nodes = [n for n in self.nodes if n.type == NodeType.END]
        if len(start_nodes) > 1:
            raise WorkflowValidationException("Workflow can have at most one start node")
        if len(end_nodes) > 1:
            raise WorkflowValidationException("Workflow can have at most one end node")


@dataclass
class NodeResult:
    """节点执行结果."""

    node_id: str
    status: NodeStatus
    output: dict[str, Any] = field(default_factory=dict)
    error: Optional[dict] = None


@dataclass
class RunResult:
    """工作流执行结果."""

    run_id: str
    status: RunStatus
    output: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0


class WorkflowEngine:
    """DAG工作流执行引擎.

    对应WAT的PhaseController + GameEngine的泛化版本。
    """

    def __init__(
        self,
        state_manager: StateManager,
        event_bus: EventBus,
        checkpoint_mgr: CheckpointManager,
        variable_pool: VariablePool,
        router_engine: RouterEngine,
    ):
        self.state_manager = state_manager
        self.event_bus = event_bus
        self.checkpoint_mgr = checkpoint_mgr
        self.variable_pool = variable_pool
        self.router_engine = router_engine

        # 节点执行器注册表
        self._executors: dict[NodeType, NodeExecutor] = {}

    def register_executor(self, node_type: NodeType, executor: "NodeExecutor") -> None:
        """注册节点执行器."""
        self._executors[node_type] = executor

    async def execute(
        self,
        workflow_def: WorkflowDefinition,
        trigger_payload: dict[str, Any],
        run_id: str,
    ) -> RunResult:
        """执行工作流的主入口.

        对应WAT GameEngine.run_game()。
        """
        # 1. 验证工作流
        workflow_def.validate()

        # 2. 自动注入start_node和end_node（如果用户未显式定义）
        workflow_def = self._auto_inject_boundary_nodes(workflow_def)

        # 3. 初始化运行状态
        state = self.state_manager.create_state(
            workflow_def=workflow_def,
            trigger_payload=trigger_payload,
            run_id=run_id,
        )

        # 4. 构建执行图
        graph = self._build_execution_graph(workflow_def)

        # 5. Super-Step执行循环
        start_time = asyncio.get_event_loop().time()
        step_count = 0
        timeout_deadline = start_time + settings.WORKFLOW_TIMEOUT_SECONDS

        try:
            while not self._is_terminal(state, graph):
                # 5.0 超时检测
                current_time = asyncio.get_event_loop().time()
                if current_time > timeout_deadline:
                    raise WorkflowExecutionException(
                        f"Workflow timeout exceeded ({settings.WORKFLOW_TIMEOUT_SECONDS}s)"
                    )

                if step_count >= settings.MAX_WORKFLOW_STEPS:
                    raise WorkflowExecutionException(
                        f"Max workflow steps ({settings.MAX_WORKFLOW_STEPS}) exceeded"
                    )

                # 5.1 获取当前可执行节点
                ready_nodes = self._get_ready_nodes(graph, state)
                if not ready_nodes:
                    # 没有就绪节点但还未终止，检查是否所有非终态节点都被阻塞
                    if self._all_nodes_blocked(state, graph):
                        break
                    # 可能是HITL暂停，等待后继续检查
                    await asyncio.sleep(0.1)
                    continue

                # 5.2 并行执行就绪节点
                tasks = [
                    self._execute_node(node, state, run_id)
                    for node in ready_nodes
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # 5.3 合并结果到状态
                for node, result in zip(ready_nodes, results):
                    if isinstance(result, Exception):
                        await self._handle_node_error(node, result, state)
                    else:
                        state = self._merge_result(state, node, result)

                # 5.4 Checkpoint持久化
                await self.checkpoint_mgr.save(run_id, state)

                # 5.5 广播状态更新
                await self.event_bus.publish(
                    {
                        "type": "run_state_update",
                        "run_id": run_id,
                        "state": state.to_dict(),
                    }
                )

                step_count += 1

            # 6. 执行完成 - 检查是否所有节点都已处理
            self._finalize_state(state, graph)

            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)

        except Exception as e:
            state.status = RunStatus.FAILED
            state.error = {"type": type(e).__name__, "message": str(e)}
            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
            raise

        finally:
            await self.state_manager.update_status(run_id, state.status)
            await self.checkpoint_mgr.save(run_id, state)

        return RunResult(
            run_id=run_id,
            status=state.status,
            output=state.output,
            duration_ms=duration_ms,
        )

    async def pause(self, run_id: str) -> None:
        """暂停执行（用于HITL或手动干预）."""
        await self.state_manager.update_status(run_id, RunStatus.PAUSED)

    async def resume(self, run_id: str, human_input: dict[str, Any]) -> None:
        """恢复执行（HITL响应后）."""
        state = await self.checkpoint_mgr.load(run_id)
        state.human_input = human_input
        await self.state_manager.update_status(run_id, RunStatus.RUNNING)
        # 重新进入执行循环（由外部调度器触发）

    async def cancel(self, run_id: str) -> None:
        """取消执行."""
        await self.state_manager.update_status(run_id, RunStatus.CANCELLED)

    async def retry(self, run_id: str, node_id: Optional[str] = None) -> None:
        """重试失败节点."""
        state = await self.checkpoint_mgr.load(run_id)
        if node_id:
            state.node_states[node_id] = NodeStatus.PENDING
        else:
            # 重试所有失败节点
            for nid, status in state.node_states.items():
                if status == NodeStatus.FAILED:
                    state.node_states[nid] = NodeStatus.PENDING
        await self.checkpoint_mgr.save(run_id, state)

    def _auto_inject_boundary_nodes(
        self, workflow_def: WorkflowDefinition
    ) -> WorkflowDefinition:
        """自动注入start_node和end_node.

        如果用户未显式定义start/end节点，自动添加:
        - start_node: 连接所有无上游的节点
        - end_node: 被所有无下游的节点连接
        """
        has_start = any(n.type == NodeType.START for n in workflow_def.nodes)
        has_end = any(n.type == NodeType.END for n in workflow_def.nodes)

        new_nodes = list(workflow_def.nodes)
        new_edges = list(workflow_def.edges)

        if not has_start:
            # 找到所有没有上游的节点（入口节点）
            all_targets = {e.target for e in workflow_def.edges}
            entry_nodes = [
                n.id for n in workflow_def.nodes
                if n.id not in all_targets and n.type != NodeType.START
            ]

            start_node = Node(
                id="__start__",
                type=NodeType.START,
                config={"auto_injected": True},
            )
            new_nodes.insert(0, start_node)

            # 连接start_node到所有入口节点
            for entry_id in entry_nodes:
                new_edges.append(Edge(source="__start__", target=entry_id))

            # 如果没有入口节点（空图或全连通），连接到第一个非end节点
            if not entry_nodes:
                first_node = next(
                    (n for n in workflow_def.nodes if n.type != NodeType.END),
                    None,
                )
                if first_node:
                    new_edges.append(Edge(source="__start__", target=first_node.id))

        if not has_end:
            # 找到所有没有下游的节点（出口节点）
            all_sources = {e.source for e in workflow_def.edges}
            exit_nodes = [
                n.id for n in workflow_def.nodes
                if n.id not in all_sources and n.type != NodeType.END
            ]

            end_node = Node(
                id="__end__",
                type=NodeType.END,
                config={"auto_injected": True},
            )
            new_nodes.append(end_node)

            # 连接所有出口节点到end_node
            for exit_id in exit_nodes:
                new_edges.append(Edge(source=exit_id, target="__end__"))

        return WorkflowDefinition(nodes=new_nodes, edges=new_edges)

    def _build_execution_graph(self, workflow_def: WorkflowDefinition) -> dict[str, Node]:
        """构建执行图."""
        return {node.id: node for node in workflow_def.nodes}

    def _is_terminal(self, state: WorkflowState, graph: dict[str, Node]) -> bool:
        """检查是否到达终止状态.

        终止条件:
        1. 状态被标记为COMPLETED/FAILED/CANCELLED
        2. 所有节点都已执行完毕（SUCCEEDED/SKIPPED/FAILED）
        3. 没有可执行的节点且end_node已完成
        """
        # 显式终止状态
        if state.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
            return True

        # 检查是否所有节点都已处理
        for node_id, node in graph.items():
            node_status = state.node_states.get(node_id)
            if node_status is None:
                return False
            if node_status not in (
                NodeStatus.SUCCEEDED,
                NodeStatus.SKIPPED,
                NodeStatus.FAILED,
            ):
                return False

        return True

    def _all_nodes_blocked(self, state: WorkflowState, graph: dict[str, Node]) -> bool:
        """检查是否所有非终态节点都被阻塞（依赖未满足）."""
        for node_id, node in graph.items():
            node_status = state.node_states.get(node_id)
            if node_status in (NodeStatus.PENDING, NodeStatus.RUNNING):
                # 检查该节点是否有未满足的依赖
                deps_satisfied = all(
                    state.node_states.get(dep) in (NodeStatus.SUCCEEDED, NodeStatus.SKIPPED)
                    for dep in node.depends_on
                )
                if deps_satisfied:
                    # 有就绪节点但未被选中，说明不是阻塞
                    return False
        return True

    def _finalize_state(self, state: WorkflowState, graph: dict[str, Node]) -> None:
        """最终化工作流状态.

        如果工作流自然结束（非异常），设置适当的状态:
        - 如果有失败节点: FAILED
        - 否则: COMPLETED
        """
        has_failed = any(
            status == NodeStatus.FAILED
            for status in state.node_states.values()
        )

        if has_failed:
            state.status = RunStatus.FAILED
            state.error = {"type": "NodeExecutionError", "message": "One or more nodes failed"}
        else:
            state.status = RunStatus.COMPLETED

        # 如果没有显式end_node输出，聚合所有节点输出
        if not state.output:
            end_node = next(
                (n for n in graph.values() if n.type == NodeType.END),
                None,
            )
            if end_node and end_node.id in state.node_outputs:
                state.output = state.node_outputs[end_node.id]
            else:
                state.output = dict(state.node_outputs)

    def _get_ready_nodes(
        self, graph: dict[str, Node], state: WorkflowState
    ) -> list[Node]:
        """获取当前可执行的节点（依赖全部满足）."""
        ready = []
        for node_id, node in graph.items():
            if state.node_states.get(node_id) != NodeStatus.PENDING:
                continue
            # 检查所有依赖是否已完成
            deps_satisfied = all(
                state.node_states.get(dep) in (NodeStatus.SUCCEEDED, NodeStatus.SKIPPED)
                for dep in node.depends_on
            )
            if deps_satisfied:
                ready.append(node)
        return ready

    async def _execute_node(
        self,
        node: Node,
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        """执行单个节点."""
        # 更新节点状态为运行中
        state.node_states[node.id] = NodeStatus.RUNNING

        # 解析节点输入（变量替换）
        inputs = self.variable_pool.resolve(
            node.config.get("inputs", {}),
            state,
        )

        # 根据节点类型分派执行器
        executor = self._executors.get(node.type)
        if not executor:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"message": f"No executor registered for node type: {node.type}"},
            )

        try:
            result = await executor.execute(node, inputs, state, run_id)
            return result
        except Exception as e:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"type": type(e).__name__, "message": str(e)},
            )

    def _merge_result(
        self,
        state: WorkflowState,
        node: Node,
        result: NodeResult,
    ) -> WorkflowState:
        """合并节点结果到全局状态."""
        state.node_states[node.id] = result.status
        if result.status == NodeStatus.SUCCEEDED:
            state.node_outputs[node.id] = result.output
        elif result.status == NodeStatus.FAILED:
            state.node_outputs[node.id] = {"error": result.error}
        return state

    async def _handle_node_error(
        self,
        node: Node,
        error: Exception,
        state: WorkflowState,
    ) -> None:
        """处理节点执行错误."""
        state.node_states[node.id] = NodeStatus.FAILED
        state.node_outputs[node.id] = {
            "error": {"type": type(error).__name__, "message": str(error)}
        }

        # 广播错误事件
        await self.event_bus.publish(
            {
                "type": "node_error",
                "node_id": node.id,
                "error": str(error),
            }
        )


class NodeExecutor:
    """节点执行器基类."""

    async def execute(
        self,
        node: Node,
        inputs: dict[str, Any],
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        """执行节点逻辑."""
        raise NotImplementedError

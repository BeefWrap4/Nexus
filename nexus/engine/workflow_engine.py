"""DAG workflow execution engine."""

from __future__ import annotations

import asyncio
from typing import Optional

from nexus.config import settings
from nexus.engine.checkpoint import CheckpointManager
from nexus.engine.enums import NodeStatus, NodeType, RunStatus
from nexus.engine.event_bus import EventBus
from nexus.engine.router_engine import RouterEngine
from nexus.engine.state_manager import StateManager, WorkflowState
from nexus.engine.variable_pool import VariablePool
from nexus.engine.workflow_graph import (
    all_nodes_blocked,
    auto_inject_boundary_nodes,
    build_execution_graph,
    finalize_state,
    get_ready_nodes,
    is_terminal,
)
from nexus.engine.workflow_types import (
    Edge,
    Node,
    NodeExecutor,
    NodeResult,
    RunResult,
    WorkflowDefinition,
)
from nexus.exceptions import WorkflowExecutionException


class WorkflowEngine:
    """Orchestrates DAG execution, persistence, and run lifecycle."""

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
        self._executors: dict[NodeType, NodeExecutor] = {}

    def register_executor(self, node_type: NodeType, executor: NodeExecutor) -> None:
        self._executors[node_type] = executor

    async def execute(
        self,
        workflow_def: WorkflowDefinition,
        trigger_payload: dict,
        run_id: str,
    ) -> RunResult:
        workflow_def.validate()
        workflow_def = self._auto_inject_boundary_nodes(workflow_def)

        state = self.state_manager.create_state(
            workflow_def=workflow_def,
            trigger_payload=trigger_payload,
            run_id=run_id,
        )
        graph = self._build_execution_graph(workflow_def)

        loop = asyncio.get_event_loop()
        start_time = loop.time()
        step_count = 0
        timeout_deadline = start_time + settings.WORKFLOW_TIMEOUT_SECONDS

        try:
            while not self._is_terminal(state, graph):
                current_time = asyncio.get_event_loop().time()
                if current_time > timeout_deadline:
                    raise WorkflowExecutionException(
                        f"Workflow timeout exceeded "
                        f"({settings.WORKFLOW_TIMEOUT_SECONDS}s)"
                    )

                if step_count >= settings.MAX_WORKFLOW_STEPS:
                    raise WorkflowExecutionException(
                        f"Max workflow steps ({settings.MAX_WORKFLOW_STEPS}) exceeded"
                    )

                ready_nodes = self._get_ready_nodes(graph, state)
                if not ready_nodes:
                    if self._all_nodes_blocked(state, graph):
                        break
                    await asyncio.sleep(0.1)
                    continue

                tasks = [self._execute_node(node, state, run_id) for node in ready_nodes]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for node, result in zip(ready_nodes, results):
                    if isinstance(result, Exception):
                        await self._handle_node_error(node, result, state)
                    else:
                        state = self._merge_result(state, node, result)

                await self.checkpoint_mgr.save(run_id, state)
                await self.event_bus.publish(
                    {
                        "type": "run_state_update",
                        "run_id": run_id,
                        "state": state.to_dict(),
                    }
                )

                step_count += 1

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
        await self.state_manager.update_status(run_id, RunStatus.PAUSED)

    async def resume(self, run_id: str, human_input: dict) -> None:
        state = await self.checkpoint_mgr.load(run_id)
        state.human_input = human_input
        await self.state_manager.update_status(run_id, RunStatus.RUNNING)

    async def cancel(self, run_id: str) -> None:
        await self.state_manager.update_status(run_id, RunStatus.CANCELLED)

    async def retry(self, run_id: str, node_id: Optional[str] = None) -> None:
        state = await self.checkpoint_mgr.load(run_id)
        if node_id:
            state.node_states[node_id] = NodeStatus.PENDING
        else:
            for nid, status in state.node_states.items():
                if status == NodeStatus.FAILED:
                    state.node_states[nid] = NodeStatus.PENDING
        await self.checkpoint_mgr.save(run_id, state)

    def _auto_inject_boundary_nodes(
        self, workflow_def: WorkflowDefinition
    ) -> WorkflowDefinition:
        return auto_inject_boundary_nodes(workflow_def)

    def _build_execution_graph(self, workflow_def: WorkflowDefinition) -> dict[str, Node]:
        return build_execution_graph(workflow_def)

    def _is_terminal(self, state: WorkflowState, graph: dict[str, Node]) -> bool:
        return is_terminal(state, graph)

    def _all_nodes_blocked(self, state: WorkflowState, graph: dict[str, Node]) -> bool:
        return all_nodes_blocked(state, graph)

    def _finalize_state(self, state: WorkflowState, graph: dict[str, Node]) -> None:
        finalize_state(state, graph)

    def _get_ready_nodes(
        self, graph: dict[str, Node], state: WorkflowState
    ) -> list[Node]:
        return get_ready_nodes(graph, state)

    async def _execute_node(
        self,
        node: Node,
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        state.node_states[node.id] = NodeStatus.RUNNING

        inputs = self.variable_pool.resolve(
            node.config.get("inputs", {}),
            state,
        )

        executor = self._executors.get(node.type)
        if not executor:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"message": f"No executor registered for node type: {node.type}"},
            )

        try:
            return await executor.execute(node, inputs, state, run_id)
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
        state.node_states[node.id] = NodeStatus.FAILED
        state.node_outputs[node.id] = {
            "error": {"type": type(error).__name__, "message": str(error)}
        }

        await self.event_bus.publish(
            {
                "type": "node_error",
                "node_id": node.id,
                "error": str(error),
            }
        )


__all__ = [
    "Edge",
    "Node",
    "NodeExecutor",
    "NodeResult",
    "RunResult",
    "WorkflowDefinition",
    "WorkflowEngine",
]

"""Graph and state helpers for WorkflowEngine."""

from __future__ import annotations

from nexus.engine.enums import NodeStatus, NodeType, RunStatus
from nexus.engine.state_manager import WorkflowState
from nexus.engine.workflow_types import Edge, Node, WorkflowDefinition


def auto_inject_boundary_nodes(workflow_def: WorkflowDefinition) -> WorkflowDefinition:
    """Inject start/end nodes when a definition omits them."""
    has_start = any(n.type == NodeType.START for n in workflow_def.nodes)
    has_end = any(n.type == NodeType.END for n in workflow_def.nodes)

    new_nodes = list(workflow_def.nodes)
    new_edges = list(workflow_def.edges)

    if not has_start:
        all_targets = {e.target for e in workflow_def.edges}
        entry_nodes = [
            n.id
            for n in workflow_def.nodes
            if n.id not in all_targets and n.type != NodeType.START
        ]

        start_node = Node(
            id="__start__",
            type=NodeType.START,
            config={"auto_injected": True},
        )
        new_nodes.insert(0, start_node)

        for entry_id in entry_nodes:
            new_edges.append(Edge(source="__start__", target=entry_id))

        if not entry_nodes:
            first_node = next(
                (n for n in workflow_def.nodes if n.type != NodeType.END),
                None,
            )
            if first_node:
                new_edges.append(Edge(source="__start__", target=first_node.id))

    if not has_end:
        all_sources = {e.source for e in workflow_def.edges}
        exit_nodes = [
            n.id
            for n in workflow_def.nodes
            if n.id not in all_sources and n.type != NodeType.END
        ]

        end_node = Node(
            id="__end__",
            type=NodeType.END,
            config={"auto_injected": True},
        )
        new_nodes.append(end_node)

        for exit_id in exit_nodes:
            new_edges.append(Edge(source=exit_id, target="__end__"))

    edge_sources: dict[str, set[str]] = {}
    for edge in new_edges:
        if edge.target not in edge_sources:
            edge_sources[edge.target] = set()
        edge_sources[edge.target].add(edge.source)

    for node in new_nodes:
        existing = set(node.depends_on)
        node.depends_on = list(existing | edge_sources.get(node.id, set()))

    return WorkflowDefinition(nodes=new_nodes, edges=new_edges)


def build_execution_graph(workflow_def: WorkflowDefinition) -> dict[str, Node]:
    return {node.id: node for node in workflow_def.nodes}


def is_terminal(state: WorkflowState, graph: dict[str, Node]) -> bool:
    if state.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
        return True

    for node_id in graph:
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


def all_nodes_blocked(state: WorkflowState, graph: dict[str, Node]) -> bool:
    for node_id, node in graph.items():
        node_status = state.node_states.get(node_id)
        if node_status in (NodeStatus.PENDING, NodeStatus.RUNNING):
            deps_satisfied = all(
                state.node_states.get(dep) in (NodeStatus.SUCCEEDED, NodeStatus.SKIPPED)
                for dep in node.depends_on
            )
            if deps_satisfied:
                return False
    return True


def finalize_state(state: WorkflowState, graph: dict[str, Node]) -> None:
    has_failed = any(status == NodeStatus.FAILED for status in state.node_states.values())

    if has_failed:
        state.status = RunStatus.FAILED
        state.error = {
            "type": "NodeExecutionError",
            "message": "One or more nodes failed",
        }
    else:
        state.status = RunStatus.COMPLETED

    if not state.output:
        end_node = next(
            (n for n in graph.values() if n.type == NodeType.END),
            None,
        )
        if end_node and end_node.id in state.node_outputs:
            state.output = state.node_outputs[end_node.id]
        else:
            state.output = dict(state.node_outputs)


def get_ready_nodes(graph: dict[str, Node], state: WorkflowState) -> list[Node]:
    ready = []
    for node_id, node in graph.items():
        if state.node_states.get(node_id) != NodeStatus.PENDING:
            continue

        deps_satisfied = all(
            state.node_states.get(dep) in (NodeStatus.SUCCEEDED, NodeStatus.SKIPPED)
            for dep in node.depends_on
        )
        if deps_satisfied:
            ready.append(node)
    return ready

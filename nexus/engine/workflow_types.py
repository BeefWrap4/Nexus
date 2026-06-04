"""Workflow domain types and executor contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from nexus.engine.enums import NodeStatus, NodeType, RunStatus

if TYPE_CHECKING:
    from nexus.engine.state_manager import WorkflowState


@dataclass
class Node:
    """Workflow node definition."""

    id: str
    type: NodeType
    config: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class Edge:
    """Directed workflow edge definition."""

    source: str
    target: str
    condition: Optional[str] = None


@dataclass
class WorkflowDefinition:
    """Workflow graph definition."""

    nodes: list[Node]
    edges: list[Edge]

    def get_node(self, node_id: str) -> Optional[Node]:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def get_dependencies(self, node_id: str) -> list[str]:
        node = self.get_node(node_id)
        return node.depends_on if node else []

    def get_downstream(self, node_id: str) -> list[str]:
        return [e.target for e in self.edges if e.source == node_id]

    def get_upstream(self, node_id: str) -> list[str]:
        return [e.source for e in self.edges if e.target == node_id]

    def validate(self) -> None:
        from nexus.exceptions import CircularDependencyException, WorkflowValidationException

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

        start_nodes = [n for n in self.nodes if n.type == NodeType.START]
        end_nodes = [n for n in self.nodes if n.type == NodeType.END]
        if len(start_nodes) > 1:
            raise WorkflowValidationException("Workflow can have at most one start node")
        if len(end_nodes) > 1:
            raise WorkflowValidationException("Workflow can have at most one end node")


@dataclass
class NodeResult:
    """Single node execution result."""

    node_id: str
    status: NodeStatus
    output: dict[str, Any] = field(default_factory=dict)
    error: Optional[dict] = None


@dataclass
class RunResult:
    """Workflow execution result."""

    run_id: str
    status: RunStatus
    output: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0


class NodeExecutor:
    """Base contract for workflow node executors."""

    async def execute(
        self,
        node: Node,
        inputs: dict[str, Any],
        state: "WorkflowState",
        run_id: str,
    ) -> NodeResult:
        raise NotImplementedError

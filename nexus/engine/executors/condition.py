"""Conditional branch workflow node executor."""

from __future__ import annotations

from typing import Any

from nexus.engine.enums import NodeStatus
from nexus.engine.router_engine import RouterEngine
from nexus.engine.state_manager import WorkflowState
from nexus.engine.workflow_engine import Node, NodeExecutor, NodeResult


class ConditionNodeExecutor(NodeExecutor):
    """Evaluate branch conditions and mark unmatched branches as skipped."""

    def __init__(
        self,
        router_engine: RouterEngine,
        workflow_def: Any = None,
    ):
        self.router_engine = router_engine
        self.workflow_def = workflow_def

    async def execute(
        self,
        node: Node,
        inputs: dict[str, Any],
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        config = node.config
        conditions = config.get("conditions", [])

        if not conditions:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.SUCCEEDED,
                output={"matched_branch": None, "result": True},
            )

        matched_branch = None
        for branch in conditions:
            condition_expr = branch.get("expression", "")
            branch_id = branch.get("branch_id", "")

            result = self.router_engine.evaluate_condition(condition_expr, state)
            if result:
                matched_branch = branch_id
                break

        if matched_branch is None:
            matched_branch = config.get("default_branch")

        if self.workflow_def and matched_branch is not None:
            await self._skip_unmatched_branches(node, matched_branch, state)

        return NodeResult(
            node_id=node.id,
            status=NodeStatus.SUCCEEDED,
            output={
                "matched_branch": matched_branch,
                "result": matched_branch is not None,
            },
        )

    async def _skip_unmatched_branches(
        self,
        node: Node,
        matched_branch: str,
        state: WorkflowState,
    ) -> None:
        if not self.workflow_def:
            return

        downstream = self.workflow_def.get_downstream(node.id)

        matched_downstream = set()
        for edge in self.workflow_def.edges:
            if edge.source == node.id:
                if edge.condition == matched_branch:
                    matched_downstream.add(edge.target)

        for target_id in downstream:
            if target_id not in matched_downstream:
                state.node_states[target_id] = NodeStatus.SKIPPED

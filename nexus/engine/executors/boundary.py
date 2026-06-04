"""Boundary node executors for workflow start and end nodes."""

from __future__ import annotations

from typing import Any

from nexus.engine.enums import NodeStatus, RunStatus
from nexus.engine.state_manager import WorkflowState
from nexus.engine.variable_pool import VariablePool
from nexus.engine.workflow_engine import Node, NodeExecutor, NodeResult


class StartNodeExecutor(NodeExecutor):
    """Inject trigger payload data into workflow run variables."""

    async def execute(
        self,
        node: Node,
        inputs: dict[str, Any],
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        payload_mapping = node.config.get("output_mapping", {})
        if payload_mapping:
            for var_name, payload_key in payload_mapping.items():
                state.run_vars[var_name] = state.trigger_payload.get(payload_key)
        else:
            state.run_vars["trigger"] = state.trigger_payload

        return NodeResult(
            node_id=node.id,
            status=NodeStatus.SUCCEEDED,
            output={"trigger_payload": state.trigger_payload},
        )


class EndNodeExecutor(NodeExecutor):
    """Aggregate final workflow output."""

    async def execute(
        self,
        node: Node,
        inputs: dict[str, Any],
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        output_config = node.config.get("output", {})
        final_output = {}

        if "expression" in output_config:
            variable_pool = VariablePool()
            resolved = variable_pool.resolve(output_config["expression"], state)
            final_output["result"] = resolved
        elif "mappings" in output_config:
            variable_pool = VariablePool()
            for key, expr in output_config["mappings"].items():
                final_output[key] = variable_pool.resolve(expr, state)
        else:
            final_output = dict(state.node_outputs)

        state.output = final_output
        state.status = RunStatus.COMPLETED

        return NodeResult(
            node_id=node.id,
            status=NodeStatus.SUCCEEDED,
            output=final_output,
        )

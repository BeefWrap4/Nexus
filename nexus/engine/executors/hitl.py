"""Human-in-the-loop workflow node executor."""

from __future__ import annotations

from typing import Any

from nexus.engine.enums import NodeStatus, RunStatus
from nexus.engine.executors._helpers import make_failed_result
from nexus.engine.hitl_controller import HITLController, HITLType
from nexus.engine.state_manager import WorkflowState
from nexus.engine.workflow_types import Node, NodeExecutor, NodeResult


class HITLNodeExecutor(NodeExecutor):
    """Create a HITL task, pause the workflow, and wait for a response."""

    def __init__(
        self,
        hitl_controller: HITLController = None,
        default_timeout: int = None,
    ):
        self.hitl_controller = hitl_controller
        self.default_timeout = default_timeout or 30

    async def execute(
        self,
        node: Node,
        inputs: dict[str, Any],
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        config = node.config

        task = await self.hitl_controller.create_task(
            run_id=run_id,
            node_id=node.id,
            task_type=HITLType(config.get("hitl_type", "approve")),
            title=config.get("title", "Approval Required"),
            description=config.get("description", ""),
            context={
                "inputs": inputs,
                "node_outputs": state.node_outputs,
                **config.get("extra_context", {}),
            },
            assignee_id=config.get("assignee_id"),
        )

        state.status = RunStatus.PAUSED

        try:
            timeout = config.get("timeout_seconds", self.default_timeout)
            default_on_timeout = None

            if config.get("auto_on_timeout"):
                default_on_timeout = await self.hitl_controller.get_default_timeout_response(
                    task.task_type
                )

            response = await self.hitl_controller.wait_for_response(
                task_id=task.id,
                timeout=timeout,
                default_on_timeout=default_on_timeout,
            )

            state.status = RunStatus.RUNNING
            state.human_input = {
                "task_id": task.id,
                "approved": response.approved,
                "selection": response.selection,
                "input_data": response.input_data,
                "correction": response.correction,
                "notes": response.notes,
            }

            if not response.approved:
                return NodeResult(
                    node_id=node.id,
                    status=NodeStatus.FAILED,
                    output={
                        "approved": False,
                        "notes": response.notes,
                    },
                    error={"message": f"HITL rejected: {response.notes}"},
                )

            return NodeResult(
                node_id=node.id,
                status=NodeStatus.SUCCEEDED,
                output={
                    "approved": True,
                    "selection": response.selection,
                    "input_data": response.input_data,
                    "correction": response.correction,
                    "notes": response.notes,
                },
            )

        except Exception as e:
            state.status = RunStatus.RUNNING
            return make_failed_result(node.id, e)

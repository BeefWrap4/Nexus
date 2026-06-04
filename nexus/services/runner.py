"""Workflow runtime runner used by the local API fallback path."""

from __future__ import annotations

from typing import Any

from nexus.engine.builder import build_engine_and_executors, create_engine_components


class WorkflowRunner:
    """Build and execute a workflow engine from JSON workflow config."""

    def __init__(self, event_bus=None, redis_client=None):
        self.redis_client = redis_client
        self.event_bus, self.state_manager, _, _, _ = create_engine_components(
            redis_client=redis_client,
            event_bus=event_bus,
        )

    async def execute_from_config(
        self,
        config: dict[str, Any],
        trigger_payload: dict[str, Any],
        run_id: str,
    ):
        """Build a workflow engine from config and execute it."""
        wf_def, engine, _ = build_engine_and_executors(
            config=config,
            redis_client=self.redis_client,
            event_bus=self.event_bus,
            state_manager=self.state_manager,
            register_extra=False,
        )

        await self.event_bus.publish(
            {
                "type": "run_started",
                "run_id": run_id,
                "workflow_nodes": [n.id for n in wf_def.nodes],
            }
        )

        result = await engine.execute(wf_def, trigger_payload, run_id)

        state = engine.state_manager.get_state(run_id)
        await self.event_bus.publish(
            {
                "type": "run_completed",
                "run_id": run_id,
                "status": result.status.value,
                "duration_ms": result.duration_ms,
                "node_states": {
                    nid: ns.value
                    for nid, ns in (state.node_states if state else {}).items()
                },
            }
        )

        return result

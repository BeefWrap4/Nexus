"""Shared factory for workflow runtime assembly.

This module is the single entry point for:
- parsing workflow JSON config into a DAG definition
- creating engine runtime components
- registering node executors consistently for API fallback and ARQ workers
"""

from __future__ import annotations

from typing import Any

from nexus.config import settings
from nexus.engine.checkpoint import CheckpointManager
from nexus.engine.enums import NodeType
from nexus.engine.event_bus import EventBus
from nexus.engine.executors import (
    AgentNodeExecutor,
    ConditionNodeExecutor,
    CrewNodeExecutor,
    EndNodeExecutor,
    HITLNodeExecutor,
    StartNodeExecutor,
    ToolNodeExecutor,
)
from nexus.engine.hitl_controller import HITLController
from nexus.engine.router_engine import RouterEngine
from nexus.engine.state_manager import StateManager
from nexus.engine.variable_pool import VariablePool
from nexus.engine.workflow_engine import WorkflowEngine
from nexus.engine.workflow_types import Edge, Node, WorkflowDefinition


def parse_workflow_definition(config: dict[str, Any]) -> WorkflowDefinition:
    """Parse workflow JSON config into a workflow definition."""
    nodes = []
    for n in config.get("nodes", []):
        nodes.append(
            Node(
                id=n["id"],
                type=NodeType(n.get("type", "agent")),
                config=n.get("config", {}),
                depends_on=n.get("depends_on", []),
            )
        )

    edges = []
    for e in config.get("edges", []):
        edges.append(
            Edge(
                source=e["source"],
                target=e["target"],
                condition=e.get("condition"),
            )
        )

    return WorkflowDefinition(nodes=nodes, edges=edges)


def create_engine_components(
    redis_client=None,
    *,
    event_bus: EventBus | None = None,
    state_manager: StateManager | None = None,
    checkpoint_mgr: CheckpointManager | None = None,
    variable_pool: VariablePool | None = None,
    router_engine: RouterEngine | None = None,
) -> tuple[EventBus, StateManager, CheckpointManager, VariablePool, RouterEngine]:
    """Create or reuse the core runtime components for WorkflowEngine."""
    event_bus = event_bus or EventBus(redis_client=redis_client)
    state_manager = state_manager or StateManager(redis_client=redis_client)
    checkpoint_mgr = checkpoint_mgr or CheckpointManager()
    variable_pool = variable_pool or VariablePool()
    router_engine = router_engine or RouterEngine()
    return event_bus, state_manager, checkpoint_mgr, variable_pool, router_engine


def build_engine(
    event_bus: EventBus,
    state_manager: StateManager,
    checkpoint_mgr: CheckpointManager,
    variable_pool: VariablePool,
    router_engine: RouterEngine,
) -> WorkflowEngine:
    """Create a workflow engine without registering node executors."""
    return WorkflowEngine(
        state_manager=state_manager,
        event_bus=event_bus,
        checkpoint_mgr=checkpoint_mgr,
        variable_pool=variable_pool,
        router_engine=router_engine,
    )


def _create_memory_backend(redis_client=None):
    """Create an agent memory backend with a safe in-memory fallback."""
    from nexus.agent.memory_backend import create_memory_backend

    try:
        if settings.AGENT_MEMORY_BACKEND == "redis" and redis_client:
            return create_memory_backend("redis", redis_client)
        return create_memory_backend("memory")
    except Exception:
        return create_memory_backend("memory")


def register_base_executors(
    engine: WorkflowEngine,
    event_bus: EventBus,
    *,
    tool_registry=None,
    memory_backend=None,
    redis_client=None,
    register_extra: bool = False,
) -> dict[str, Any]:
    """Register the standard node executors on a workflow engine.

    The base registration covers START, END, AGENT, HITL, and CREW nodes.
    When ``register_extra`` is true, TOOL and CONDITION executors are also
    registered for worker-style full execution.
    """
    hitl_controller = HITLController(event_bus=event_bus)

    engine.register_executor(NodeType.START, StartNodeExecutor())
    engine.register_executor(NodeType.END, EndNodeExecutor())

    if tool_registry is None:
        from nexus.tools.registry import get_tool_registry

        tool_registry = get_tool_registry()

    if memory_backend is None:
        memory_backend = _create_memory_backend(redis_client)

    engine.register_executor(
        NodeType.AGENT,
        AgentNodeExecutor(
            tool_registry=tool_registry,
            memory_backend=memory_backend,
        ),
    )
    engine.register_executor(
        NodeType.HITL,
        HITLNodeExecutor(hitl_controller=hitl_controller, default_timeout=10),
    )
    engine.register_executor(
        NodeType.CREW,
        CrewNodeExecutor(tool_registry=tool_registry, event_bus=event_bus),
    )

    if register_extra:
        engine.register_executor(
            NodeType.TOOL,
            ToolNodeExecutor(tool_registry=tool_registry, event_bus=event_bus),
        )
        engine.register_executor(
            NodeType.CONDITION,
            ConditionNodeExecutor(router_engine=engine.router_engine),
        )

    return {"tool_registry": tool_registry, "memory_backend": memory_backend}


def build_engine_and_executors(
    config: dict[str, Any],
    *,
    redis_client=None,
    register_extra: bool = False,
    event_bus: EventBus | None = None,
    state_manager: StateManager | None = None,
    checkpoint_mgr: CheckpointManager | None = None,
    variable_pool: VariablePool | None = None,
    router_engine: RouterEngine | None = None,
    tool_registry=None,
    memory_backend=None,
) -> tuple[WorkflowDefinition, WorkflowEngine, dict[str, Any]]:
    """Build a workflow definition, engine, executors, and runtime extras."""
    wf_def = parse_workflow_definition(config)
    event_bus, state_manager, cp, vp, re_ = create_engine_components(
        redis_client,
        event_bus=event_bus,
        state_manager=state_manager,
        checkpoint_mgr=checkpoint_mgr,
        variable_pool=variable_pool,
        router_engine=router_engine,
    )
    engine = build_engine(event_bus, state_manager, cp, vp, re_)
    extras = register_base_executors(
        engine,
        event_bus,
        tool_registry=tool_registry,
        memory_backend=memory_backend,
        redis_client=redis_client,
        register_extra=register_extra,
    )
    extras.update(
        {
            "event_bus": event_bus,
            "state_manager": state_manager,
            "checkpoint_mgr": cp,
            "variable_pool": vp,
            "router_engine": re_,
        }
    )
    return wf_def, engine, extras

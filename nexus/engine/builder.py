"""工作流引擎构建工厂.

消除 runner.py 和 jobs/workflow.py 之间的 50+ 行重复代码。
统一 "解析 DAG → 创建引擎组件 → 注册执行器" 的构建链路。

用法:
    from nexus.engine.builder import build_engine_and_executors

    engine, executors = build_engine_and_executors(
        config=workflow_config,
        redis_client=redis,
    )
    result = await engine.execute(wf_def, trigger_payload, run_id)
"""

from __future__ import annotations

from typing import Any

from nexus.config import settings
from nexus.engine.checkpoint import CheckpointManager
from nexus.engine.enums import NodeType
from nexus.engine.event_bus import EventBus
from nexus.engine.hitl_controller import HITLController
from nexus.engine.executors import (
    AgentNodeExecutor,
    ConditionNodeExecutor,
    CrewNodeExecutor,
    EndNodeExecutor,
    HITLNodeExecutor,
    StartNodeExecutor,
    ToolNodeExecutor,
)
from nexus.engine.router_engine import RouterEngine
from nexus.engine.state_manager import StateManager
from nexus.engine.variable_pool import VariablePool
from nexus.engine.workflow_engine import (
    WorkflowEngine,
)
from nexus.engine.workflow_types import (
    Edge,
    Node,
    WorkflowDefinition,
)


def parse_workflow_definition(config: dict[str, Any]) -> WorkflowDefinition:
    """从 JSON config 解析工作流定义（节点 + 边）.

    Args:
        config: 包含 "nodes" 和 "edges" 键的字典

    Returns:
        WorkflowDefinition 实例
    """
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
    """创建引擎核心组件.

    Args:
        redis_client: Redis 客户端（可选，None 时使用纯内存模式）

    Returns:
        (event_bus, state_manager, checkpoint_mgr, variable_pool, router_engine)
    """
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
    """创建 WorkflowEngine 实例.

    注意：不注册执行器，需要调用方自行注册。
    """
    return WorkflowEngine(
        state_manager=state_manager,
        event_bus=event_bus,
        checkpoint_mgr=checkpoint_mgr,
        variable_pool=variable_pool,
        router_engine=router_engine,
    )


def register_base_executors(
    engine: WorkflowEngine,
    event_bus: EventBus,
    *,
    tool_registry=None,
    memory_backend=None,
    redis_client=None,
    register_extra: bool = False,
) -> dict[str, Any]:
    """注册节点执行器到引擎.

    默认注册 START、END、AGENT、HITL、CREW。
    当 register_extra=True 时额外注册 TOOL 和 CONDITION（ARQ Worker 路径）。

    Args:
        engine: WorkflowEngine 实例
        event_bus: EventBus 实例
        tool_registry: 工具注册表（可选，Worker 路径需要）
        memory_backend: Agent 内存后端（可选，Worker 路径需要）
        redis_client: Redis 客户端（可选，用于创建内存后端）
        register_extra: 是否注册额外执行器（TOOL、CONDITION）

    Returns:
        包含 tool_registry 和 memory_backend 的字典（供调用方后续使用）
    """
    hitl_controller = HITLController(event_bus=event_bus)

    engine.register_executor(NodeType.START, StartNodeExecutor())
    engine.register_executor(NodeType.END, EndNodeExecutor())

    # Agent 执行器：优先使用传入的 tool_registry/memory_backend
    if tool_registry is None:
        from nexus.tools.registry import get_tool_registry

        tool_registry = get_tool_registry()

    if memory_backend is None:
        from nexus.agent.memory_backend import create_memory_backend

        try:
            if settings.AGENT_MEMORY_BACKEND == "redis" and redis_client:
                memory_backend = create_memory_backend("redis", redis_client)
            else:
                memory_backend = create_memory_backend("memory")
        except Exception:
            memory_backend = create_memory_backend("memory")

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

    # 额外执行器（ARQ Worker 路径）
    if register_extra:
        engine.register_executor(
            NodeType.TOOL,
            ToolNodeExecutor(tool_registry=tool_registry, event_bus=event_bus),
        )
        router_engine = engine.router_engine  # 从 engine 获取
        engine.register_executor(
            NodeType.CONDITION,
            ConditionNodeExecutor(router_engine=router_engine),
        )

    return {"tool_registry": tool_registry, "memory_backend": memory_backend}


# ---------------------------------------------------------------------------
# 一站式便捷函数
# ---------------------------------------------------------------------------


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
    """一站式构建：解析 DAG + 创建组件 + 注册执行器.

    这是大多数调用方应使用的快捷入口。

    Args:
        config: 包含 "nodes" 和 "edges" 的 workflow config
        redis_client: Redis 客户端（可选）
        register_extra: 是否注册 TOOL 和 CONDITION 执行器

    Returns:
        (workflow_definition, engine, extras_dict)
        extras_dict 包含 {"tool_registry": ..., "memory_backend": ...}
    """
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
        engine, event_bus,
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

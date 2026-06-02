"""ARQ 工作流执行任务.

定义可在 ARQ Worker 中执行的顶层任务函数。
Worker 启动时通过 arq CLI 加载此模块。

关键设计:
1. 函数必须是模块级、可序列化的（不能是闭包/lambda）
2. Worker 中重建完整的引擎链路（状态不共享，通过 Redis Pub/Sub 通信）
3. 数据库状态通过独立会话更新（与引擎内存状态分离）
"""

from __future__ import annotations

import traceback
from typing import Any
from uuid import UUID

from nexus.config import settings
from nexus.db.database import get_db_session
from nexus.engine.event_bus import EventBus
from nexus.engine.workflow_engine import (
    Edge,
    Node,
    NodeType,
    WorkflowDefinition,
    WorkflowEngine,
)
from nexus.engine.state_manager import StateManager
from nexus.engine.checkpoint import CheckpointManager
from nexus.engine.variable_pool import VariablePool
from nexus.engine.router_engine import RouterEngine
from nexus.engine.node_executors import (
    StartNodeExecutor,
    EndNodeExecutor,
    AgentNodeExecutor,
    HITLNodeExecutor,
)
from nexus.engine.hitl_controller import HITLController
from nexus.engine.enums import RunStatus
from nexus.services.run import RunService


async def execute_workflow_job(
    ctx: dict[str, Any],
    run_id: str,
    workflow_config: dict[str, Any],
    trigger_payload: dict[str, Any],
    tenant_id: str,
) -> dict[str, Any]:
    """ARQ Worker 中执行工作流.

    Args:
        ctx: ARQ 上下文，包含 redis 连接等
        run_id: 工作流运行实例ID
        workflow_config: 工作流DAG配置（nodes + edges）
        trigger_payload: 触发载荷
        tenant_id: 租户ID

    Returns:
        {"run_id": str, "status": str, "duration_ms": int}

    Raises:
        执行失败时抛出异常，ARQ 会根据配置重试
    """
    import structlog

    logger = structlog.get_logger()
    redis = ctx.get("redis")

    logger.info(
        "workflow_job_started",
        run_id=run_id,
        tenant_id=tenant_id,
        worker_id=ctx.get("worker_id", "unknown"),
    )

    # 1. 更新数据库状态为 running
    async with get_db_session() as session:
        run_service = RunService()
        run = await run_service.update_status(
            session,
            run_id=UUID(run_id),
            tenant_id=UUID(tenant_id),
            status="running",
        )
        if run is None:
            raise ValueError(f"Run {run_id} not found for tenant {tenant_id}")

    # 2. 重建引擎组件（Worker 独立的内存状态）
    event_bus = EventBus(redis_client=redis)
    state_manager = StateManager()
    checkpoint_mgr = CheckpointManager()
    variable_pool = VariablePool()
    router_engine = RouterEngine()

    engine = WorkflowEngine(
        state_manager=state_manager,
        event_bus=event_bus,
        checkpoint_mgr=checkpoint_mgr,
        variable_pool=variable_pool,
        router_engine=router_engine,
    )

    # 3. 注册节点执行器
    hitl_controller = HITLController(event_bus=event_bus)
    engine.register_executor(NodeType.START, StartNodeExecutor())
    engine.register_executor(NodeType.END, EndNodeExecutor())
    engine.register_executor(NodeType.AGENT, AgentNodeExecutor())
    engine.register_executor(
        NodeType.HITL,
        HITLNodeExecutor(hitl_controller=hitl_controller, default_timeout=10),
    )

    # 4. 解析工作流定义
    nodes = []
    for n in workflow_config.get("nodes", []):
        nodes.append(
            Node(
                id=n["id"],
                type=NodeType(n.get("type", "agent")),
                config=n.get("config", {}),
                depends_on=n.get("depends_on", []),
            )
        )

    edges = []
    for e in workflow_config.get("edges", []):
        edges.append(
            Edge(
                source=e["source"],
                target=e["target"],
                condition=e.get("condition"),
            )
        )

    wf_def = WorkflowDefinition(nodes=nodes, edges=edges)

    # 5. 广播开始事件（通过 Redis Pub/Sub 传播到 API 进程）
    await event_bus.publish(
        {
            "type": "run_started",
            "run_id": run_id,
            "tenant_id": tenant_id,
            "workflow_nodes": [n.id for n in nodes],
        }
    )

    # 6. 执行工作流
    try:
        result = await engine.execute(wf_def, trigger_payload, run_id)

        # 7. 广播结束事件
        await event_bus.publish(
            {
                "type": "run_completed",
                "run_id": run_id,
                "tenant_id": tenant_id,
                "status": result.status.value,
                "duration_ms": result.duration_ms,
                "node_states": {
                    nid: ns.value
                    for nid, ns in state_manager.get_state(run_id).node_states.items()
                }
                if state_manager.get_state(run_id)
                else {},
            }
        )

        # 8. 更新数据库状态
        async with get_db_session() as session:
            await run_service.update_status(
                session,
                run_id=UUID(run_id),
                tenant_id=UUID(tenant_id),
                status=result.status.value,
                result=result.output,
                state=state_manager.get_state(run_id).to_dict()
                if state_manager.get_state(run_id)
                else {},
            )

        logger.info(
            "workflow_job_completed",
            run_id=run_id,
            status=result.status.value,
            duration_ms=result.duration_ms,
        )

        return {
            "run_id": run_id,
            "status": result.status.value,
            "duration_ms": result.duration_ms,
        }

    except Exception as exc:
        error_info = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }

        logger.error(
            "workflow_job_failed",
            run_id=run_id,
            error=error_info["message"],
            error_type=error_info["type"],
        )

        # 广播失败事件
        await event_bus.publish(
            {
                "type": "run_failed",
                "run_id": run_id,
                "tenant_id": tenant_id,
                "error": error_info,
            }
        )

        # 更新数据库状态为 failed
        async with get_db_session() as session:
            await run_service.update_status(
                session,
                run_id=UUID(run_id),
                tenant_id=UUID(tenant_id),
                status="failed",
                result={"error": error_info},
            )

        raise

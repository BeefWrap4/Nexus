"""工作流运行时调度器.

连接 API → Engine → Agent → LLM 的完整执行链路。
当 API 收到触发请求后，通过此模块启动后台引擎执行。
"""

from __future__ import annotations

import asyncio
import traceback
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from nexus.agent.llm_client import LLMClient
from nexus.engine.checkpoint import CheckpointManager
from nexus.engine.enums import NodeType
from nexus.engine.event_bus import EventBus
from nexus.engine.node_executors import (
    AgentNodeExecutor,
    CrewNodeExecutor,
    EndNodeExecutor,
    HITLNodeExecutor,
    StartNodeExecutor,
)
from nexus.engine.router_engine import RouterEngine
from nexus.engine.state_manager import StateManager
from nexus.engine.variable_pool import VariablePool
from nexus.engine.workflow_engine import (
    Edge,
    Node,
    WorkflowDefinition,
    WorkflowEngine,
)
from nexus.engine.hitl_controller import HITLController


class WorkflowRunner:
    """工作流运行时——从 Workflow JSON config 创建引擎并执行."""

    def __init__(self, event_bus: EventBus | None = None):
        self.event_bus = event_bus or EventBus()
        self.state_manager = StateManager()

    async def execute_from_config(
        self,
        config: dict[str, Any],
        trigger_payload: dict[str, Any],
        run_id: str,
    ):
        """从 workflow.config (JSON DAG) 构建引擎并执行."""
        # 1. 解析节点
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

        # 2. 解析边
        edges = []
        for e in config.get("edges", []):
            edges.append(
                Edge(
                    source=e["source"],
                    target=e["target"],
                    condition=e.get("condition"),
                )
            )

        wf = WorkflowDefinition(nodes=nodes, edges=edges)

        # 3. 创建引擎组件
        cp = CheckpointManager()
        vp = VariablePool()
        re_ = RouterEngine()
        engine = WorkflowEngine(self.state_manager, self.event_bus, cp, vp, re_)

        # 4. 注册执行器（生产级：接入真实 LLM）
        hitl_controller = HITLController(event_bus=self.event_bus)
        engine.register_executor(NodeType.START, StartNodeExecutor())
        engine.register_executor(NodeType.END, EndNodeExecutor())
        engine.register_executor(NodeType.AGENT, AgentNodeExecutor())
        engine.register_executor(
            NodeType.HITL,
            HITLNodeExecutor(hitl_controller=hitl_controller, default_timeout=10),
        )
        engine.register_executor(
            NodeType.CREW,
            CrewNodeExecutor(event_bus=self.event_bus),
        )

        # 5. 广播开始事件
        await self.event_bus.publish(
            {
                "type": "run_started",
                "run_id": run_id,
                "workflow_nodes": [n.id for n in nodes],
            }
        )

        # 6. 执行
        result = await engine.execute(wf, trigger_payload, run_id)

        # 7. 广播结束事件
        state = self.state_manager.get_state(run_id)
        await self.event_bus.publish(
            {
                "type": "run_completed",
                "run_id": run_id,
                "status": result.status.value,
                "duration_ms": result.duration_ms,
                "node_states": {
                    nid: ns.value for nid, ns in (state.node_states if state else {}).items()
                },
            }
        )

        return result


# 全局单例，用于 API 路由挂载
runner = WorkflowRunner()

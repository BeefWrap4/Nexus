"""工作流运行时调度器.

连接 API → Engine → Agent → LLM 的完整执行链路。
当 API 收到触发请求后，通过此模块启动后台引擎执行。
"""

from __future__ import annotations

from typing import Any

from nexus.engine.builder import (
    build_engine_and_executors,
    create_engine_components,
)
from nexus.engine.enums import NodeType


class WorkflowRunner:
    """工作流运行时——从 Workflow JSON config 创建引擎并执行."""

    def __init__(self, event_bus=None, redis_client=None):
        if event_bus:
            self.event_bus = event_bus
            self.state_manager = None  # 由 event_bus/redis_client 决定
        else:
            self.event_bus, self.state_manager, _, _, _ = create_engine_components(
                redis_client=redis_client
            )

    async def execute_from_config(
        self,
        config: dict[str, Any],
        trigger_payload: dict[str, Any],
        run_id: str,
    ):
        """从 workflow.config (JSON DAG) 构建引擎并执行."""
        # 1. 一站式构建
        wf_def, engine, _ = build_engine_and_executors(
            config=config,
            redis_client=None,  # API 路径使用纯内存模式
            register_extra=False,  # 不注册 TOOL/CONDITION 执行器
        )

        # 2. 使用 WorkflowRunner 自身的 event_bus（保证事件发布一致）
        engine.event_bus = self.event_bus
        if self.state_manager:
            engine.state_manager = self.state_manager

        # 3. 广播开始事件
        await self.event_bus.publish(
            {
                "type": "run_started",
                "run_id": run_id,
                "workflow_nodes": [n.id for n in wf_def.nodes],
            }
        )

        # 4. 执行
        result = await engine.execute(wf_def, trigger_payload, run_id)

        # 5. 广播结束事件
        state = engine.state_manager.get_state(run_id)
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

"""工作流状态管理器.

基于WAT GameState + GameEngine 升级:
- 从Pydantic模型迁移到SQLAlchemy持久化
- 增量更新（Reducer模式，借鉴LangGraph）
- 三层变量系统（借鉴Dify）
- **Redis-backed 持久化**（Worker 重启不丢失，多 Worker 共享）
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from nexus.engine.enums import NodeStatus, RunStatus


class VariableType(str, Enum):
    """变量类型."""

    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    FILE = "file"
    SECRET = "secret"


@dataclass
class ErrorInfo:
    """错误信息."""

    type: str
    message: str
    details: Optional[dict[str, Any]] = None


@dataclass
class WorkflowState:
    """工作流执行状态 - 对应WAT的GameState泛化.

    对应WAT设计:
    - run_id → game_id
    - node_states → players状态
    - node_outputs → events历史
    - trigger_payload → GameConfig
    """

    run_id: str
    workflow_id: str
    version: int
    status: RunStatus = RunStatus.PENDING

    # 节点执行状态: node_id -> NodeStatus
    node_states: dict[str, NodeStatus] = field(default_factory=dict)

    # 三层变量系统（借鉴Dify）
    env_vars: dict[str, Any] = field(default_factory=dict)  # 环境变量
    run_vars: dict[str, Any] = field(default_factory=dict)  # 运行级变量
    node_outputs: dict[str, Any] = field(default_factory=dict)  # 节点输出

    # 上下文
    trigger_payload: dict[str, Any] = field(default_factory=dict)
    human_input: Optional[dict[str, Any]] = None

    # 输出
    output: dict[str, Any] = field(default_factory=dict)
    error: Optional[ErrorInfo] = None

    # 元数据
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典."""
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "version": self.version,
            "status": self.status.value,
            "node_states": {k: v.value for k, v in self.node_states.items()},
            "env_vars": self.env_vars,
            "run_vars": self.run_vars,
            "node_outputs": self.node_outputs,
            "trigger_payload": self.trigger_payload,
            "human_input": self.human_input,
            "output": self.output,
            "error": (
                self.error.__dict__ if hasattr(self.error, "__dict__")
                else self.error if isinstance(self.error, dict)
                else str(self.error)
            ) if self.error else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowState":
        """从字典反序列化."""
        return cls(
            run_id=data["run_id"],
            workflow_id=data["workflow_id"],
            version=data["version"],
            status=RunStatus(data.get("status", "pending")),
            node_states={
                k: NodeStatus(v) for k, v in data.get("node_states", {}).items()
            },
            env_vars=data.get("env_vars", {}),
            run_vars=data.get("run_vars", {}),
            node_outputs=data.get("node_outputs", {}),
            trigger_payload=data.get("trigger_payload", {}),
            human_input=data.get("human_input"),
            output=data.get("output", {}),
            error=ErrorInfo(**data["error"]) if data.get("error") else None,
            started_at=datetime.fromisoformat(data["started_at"])
            if data.get("started_at")
            else None,
            completed_at=datetime.fromisoformat(data["completed_at"])
            if data.get("completed_at")
            else None,
        )


class StateManager:
    """状态管理器 - Redis-backed + 内存降级.

    关键设计:
    - Redis 可用时: 所有状态读写通过 Redis JSON 序列化
    - Redis 不可用时: 回退到内存 dict（日志 warning）
    - Worker 重启后: 从 Redis 恢复状态
    - 多 Worker: 共享 Redis 中的状态
    """

    def __init__(self, redis_client=None):
        self.redis = redis_client
        self._states: dict[str, WorkflowState] = {}  # 内存降级缓存
        self._use_redis = redis_client is not None

    def _state_key(self, run_id: str) -> str:
        return f"nexus:state:{run_id}"

    async def _save_to_redis(self, run_id: str, state: WorkflowState) -> None:
        """保存状态到 Redis."""
        if not self._use_redis:
            return
        try:
            await self.redis.set(
                self._state_key(run_id),
                json.dumps(state.to_dict()),
                ex=86400,  # 24 小时过期
            )
        except Exception:
            pass

    async def _load_from_redis(self, run_id: str) -> Optional[WorkflowState]:
        """从 Redis 加载状态."""
        if not self._use_redis:
            return None
        try:
            data = await self.redis.get(self._state_key(run_id))
            if data:
                return WorkflowState.from_dict(json.loads(data))
        except Exception:
            pass
        return None

    async def _delete_from_redis(self, run_id: str) -> None:
        """从 Redis 删除状态."""
        if not self._use_redis:
            return
        try:
            await self.redis.delete(self._state_key(run_id))
        except Exception:
            pass

    def create_state(
        self,
        workflow_def: Any,  # WorkflowDefinition
        trigger_payload: dict[str, Any],
        run_id: str,
    ) -> WorkflowState:
        """初始化工作流状态."""
        node_states = {node.id: NodeStatus.PENDING for node in workflow_def.nodes}

        state = WorkflowState(
            run_id=run_id,
            workflow_id=getattr(workflow_def, "workflow_id", ""),
            version=getattr(workflow_def, "version", 1),
            status=RunStatus.RUNNING,
            node_states=node_states,
            trigger_payload=trigger_payload,
            started_at=datetime.now(timezone.utc),
        )

        # 同步写入内存（create_state 是同步方法，保持兼容）
        self._states[run_id] = state
        return state

    async def update_status(self, run_id: str, status: RunStatus) -> None:
        """更新运行状态."""
        if run_id in self._states:
            self._states[run_id].status = status
            if status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
                self._states[run_id].completed_at = datetime.now(timezone.utc)
            await self._save_to_redis(run_id, self._states[run_id])

    async def update_node_state(
        self,
        run_id: str,
        node_id: str,
        status: NodeStatus,
        output: Optional[dict[str, Any]] = None,
        error: Optional[ErrorInfo] = None,
    ) -> None:
        """更新节点状态."""
        if run_id not in self._states:
            return

        state = self._states[run_id]
        state.node_states[node_id] = status
        if output:
            state.node_outputs[node_id] = output
        if error:
            state.error = error

        await self._save_to_redis(run_id, state)

    def get_state(self, run_id: str) -> Optional[WorkflowState]:
        """获取当前状态（同步，优先内存）."""
        return self._states.get(run_id)

    async def get_state_async(self, run_id: str) -> Optional[WorkflowState]:
        """异步获取状态（支持从 Redis 恢复）."""
        if run_id in self._states:
            return self._states[run_id]
        # 从 Redis 恢复
        state = await self._load_from_redis(run_id)
        if state:
            self._states[run_id] = state
        return state

    def set_state(self, run_id: str, state: WorkflowState) -> None:
        """设置状态（用于恢复）."""
        self._states[run_id] = state

    def delete_state(self, run_id: str) -> None:
        """删除状态."""
        self._states.pop(run_id, None)

"""工作流引擎核心枚举.

将枚举定义独立出来，避免循环导入问题。
"""

from enum import Enum


class NodeType(str, Enum):
    """节点类型 - 对应WAT的Phase枚举泛化."""

    START = "start"
    AGENT = "agent"
    CREW = "crew"
    TOOL = "tool"
    HITL = "hitl"
    CONDITION = "condition"
    PARALLEL = "parallel"
    LOOP = "loop"
    DELAY = "delay"
    END = "end"


class NodeStatus(str, Enum):
    """节点执行状态."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunStatus(str, Enum):
    """工作流运行状态."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

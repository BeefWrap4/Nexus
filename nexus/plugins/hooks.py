"""Lifecycle hooks for plugin integration."""
from enum import Enum


class HookType(str, Enum):
    WORKFLOW_PRE_EXECUTE = "workflow:pre_execute"
    WORKFLOW_POST_EXECUTE = "workflow:post_execute"
    NODE_PRE_EXECUTE = "node:pre_execute"
    NODE_POST_EXECUTE = "node:post_execute"
    AGENT_PRE_DECISION = "agent:pre_decision"
    AGENT_POST_DECISION = "agent:post_decision"
    LLM_PRE_CALL = "llm:pre_call"
    LLM_POST_CALL = "llm:post_call"
    HITL_PRE_APPROVAL = "hitl:pre_approval"
    HITL_POST_APPROVAL = "hitl:post_approval"


class Hook:
    """钩子定义."""
    def __init__(self, hook_type: HookType, handler: callable, priority: int = 0):
        self.type = hook_type
        self.handler = handler
        self.priority = priority  # 越小越先执行

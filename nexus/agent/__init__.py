"""NEXUS Agent运行时.

基于WAT agent/ 升级:
- BaseAgent泛化为企业级Agent（移除狼人杀专属逻辑）
- LLMClient复用（增加LiteLLM Proxy集成）
- DecisionParser复用（扩展Tool Call解析）
- TrustModel泛化为通用信任评估
- 新增AgentMemory（短期+长期记忆）
- 新增MultiModal支持（图像/音频/视频）
"""

from nexus.agent.base import BaseAgent, AgentConfig, AgentResult, Task
from nexus.agent.llm_client import LLMClient
from nexus.agent.decision_parser import DecisionParser, AgentDecision
from nexus.agent.trust_model import TrustModel
from nexus.agent.memory import AgentMemory
from nexus.agent.multimodal import (
    MediaInput,
    MediaType,
    MultiModalMessage,
    MultiModalTask,
    is_vision_model,
    build_multimodal_messages,
)

__all__ = [
    "BaseAgent",
    "AgentConfig",
    "AgentResult",
    "Task",
    "LLMClient",
    "DecisionParser",
    "AgentDecision",
    "TrustModel",
    "AgentMemory",
    "MediaInput",
    "MediaType",
    "MultiModalMessage",
    "MultiModalTask",
    "is_vision_model",
    "build_multimodal_messages",
]

"""节点执行器公共 helper 函数.

提取跨执行器的重复逻辑，减少代码冗余。
"""

from __future__ import annotations

from typing import Any

from nexus.agent.base import AgentConfig
from nexus.config import settings
from nexus.engine.enums import NodeStatus
from nexus.engine.workflow_types import NodeResult


def make_failed_result(node_id: str, error: Exception) -> NodeResult:
    """从异常创建 FAILED NodeResult.

    统一所有执行器的异常处理返回格式。

    Args:
        node_id: 节点ID
        error: 捕获的异常

    Returns:
        状态为 FAILED 的 NodeResult
    """
    return NodeResult(
        node_id=node_id,
        status=NodeStatus.FAILED,
        error={"type": type(error).__name__, "message": str(error)},
    )


def build_agent_config_from_model(agent_model: Any) -> AgentConfig:
    """从 AgentModel DB 记录构建 AgentConfig.

    统一 CrewNodeExecutor 和 CrewExecutionService 的 Agent 配置构建逻辑。

    Args:
        agent_model: AgentModel ORM 实例

    Returns:
        AgentConfig 实例
    """
    llm = agent_model.llm_settings or {}
    return AgentConfig(
        name=agent_model.name,
        role=agent_model.role or "",
        goal=agent_model.goal or "",
        backstory=agent_model.backstory or "",
        system_prompt=agent_model.system_prompt or "",
        provider=llm.get("provider", settings.DEFAULT_LLM_PROVIDER),
        model=llm.get("model", settings.DEFAULT_LLM_MODEL),
        temperature=llm.get("temperature", settings.DEFAULT_LLM_TEMPERATURE),
        max_tokens=llm.get("max_tokens", settings.DEFAULT_LLM_MAX_TOKENS),
        max_iterations=agent_model.max_iterations or settings.DEFAULT_MAX_ITERATIONS,
        tools=agent_model.tools or [],
    )

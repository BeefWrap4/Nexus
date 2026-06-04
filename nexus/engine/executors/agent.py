"""Agent workflow node executor."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from nexus.agent.base import AgentConfig, BaseAgent, Task
from nexus.config import settings
from nexus.engine.executors.llm import create_llm_client
from nexus.engine.enums import NodeStatus
from nexus.engine.state_manager import WorkflowState
from nexus.engine.workflow_engine import Node, NodeExecutor, NodeResult
from nexus.observability.llm_tracer import TRACE_CONTEXT, set_trace_context


class AgentNodeExecutor(NodeExecutor):
    """Create a BaseAgent from node config and execute its task."""

    def __init__(
        self,
        agent_factory: Any = None,
        default_agent: BaseAgent = None,
        tool_registry: Any = None,
        memory_backend: Any = None,
    ):
        self.agent_factory = agent_factory
        self.default_agent = default_agent
        self.tool_registry = tool_registry
        self.memory_backend = memory_backend
        self._agent_cache: dict[str, BaseAgent] = {}

    async def execute(
        self,
        node: Node,
        inputs: dict[str, Any],
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        config = node.config

        agent_name = config.get("agent_name", f"agent_{node.id}")
        agent_role = config.get("agent_role", "")
        agent_goal = config.get("agent_goal", "")
        task_description = config.get("task_description", config.get("task", ""))
        tools_list = config.get("tools", [])

        model = config.get("model", settings.DEFAULT_LLM_MODEL)
        provider = config.get("provider", settings.DEFAULT_LLM_PROVIDER)
        llm_client = create_llm_client({"provider": provider})

        memory = None
        if self.memory_backend and settings.AGENT_MEMORY_ENABLED:
            from nexus.agent.memory import AgentMemory

            memory = AgentMemory(
                agent_id=f"{run_id}:{node.id}",
                backend=self.memory_backend,
            )

        template_id = config.get("system_prompt_template_id")
        if template_id and isinstance(template_id, str):
            template_id = UUID(template_id)

        agent_config = AgentConfig(
            name=agent_name,
            role=agent_role,
            goal=agent_goal,
            system_prompt=config.get("system_prompt", ""),
            system_prompt_template_id=template_id,
            template_variables=config.get("template_variables", {}),
            provider=provider,
            model=model,
            temperature=config.get("temperature", settings.DEFAULT_LLM_TEMPERATURE),
            max_tokens=config.get("max_tokens", settings.DEFAULT_LLM_MAX_TOKENS),
            max_iterations=config.get("max_iterations", settings.DEFAULT_MAX_ITERATIONS),
            tools=tools_list,
            memory_enabled=settings.AGENT_MEMORY_ENABLED,
            enable_semantic_cache=config.get("enable_semantic_cache", False),
        )
        agent = BaseAgent(
            config=agent_config,
            llm_client=llm_client,
            memory=memory,
            tool_registry=self.tool_registry,
        )
        task = Task(description=task_description)

        trace_token = set_trace_context(
            run_id=run_id,
            node_id=node.id,
            tenant_id=state.env_vars.get("tenant_id"),
        )
        try:
            result = await agent.execute(
                task,
                context={
                    "run_id": run_id,
                    "node_id": node.id,
                    "tenant_id": state.env_vars.get("tenant_id"),
                    "user_id": state.env_vars.get("user_id"),
                },
            )

            output_key = config.get("output_key", node.id)
            state.run_vars[output_key] = result.output

            return NodeResult(
                node_id=node.id,
                status=NodeStatus.SUCCEEDED,
                output={
                    "output": result.output,
                    "reasoning": result.reasoning,
                    "tool_calls": result.tool_calls,
                    "confidence": result.confidence,
                },
            )
        except Exception as e:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"type": type(e).__name__, "message": str(e)},
            )
        finally:
            TRACE_CONTEXT.reset(trace_token)

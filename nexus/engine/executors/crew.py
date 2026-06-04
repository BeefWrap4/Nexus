"""Crew workflow node executor."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from nexus.agent.base import AgentConfig, BaseAgent
from nexus.agent.crew import Crew, CrewConfig, CrewMode
from nexus.agent.llm_client import LLMClient
from nexus.config import settings
from nexus.db.database import AsyncSessionLocal
from nexus.engine.executors.llm import create_llm_client
from nexus.engine.enums import NodeStatus
from nexus.engine.state_manager import WorkflowState
from nexus.engine.workflow_types import Node, NodeExecutor, NodeResult
from nexus.models.agent import Agent as AgentModel
from nexus.models.crew import Crew as CrewModel
from nexus.models.crew import CrewAgent as CrewAgentModel


class CrewNodeExecutor(NodeExecutor):
    """Load a Crew definition from the database and execute it as one node."""

    def __init__(
        self,
        tool_registry: Any = None,
        event_bus: Any = None,
    ):
        self.tool_registry = tool_registry
        self.event_bus = event_bus

    async def execute(
        self,
        node: Node,
        inputs: dict[str, Any],
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        config = node.config

        crew_id = config.get("crew_id")
        task_description = config.get("task_description", config.get("task", ""))

        if not crew_id:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"message": "crew_id not specified in node config"},
            )

        if not task_description:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"message": "task_description not specified in node config"},
            )

        try:
            if isinstance(crew_id, str):
                crew_id = UUID(crew_id)

            async with AsyncSessionLocal() as session:
                crew_record = await session.get(CrewModel, crew_id)
                if not crew_record:
                    return NodeResult(
                        node_id=node.id,
                        status=NodeStatus.FAILED,
                        error={"message": f"Crew '{crew_id}' not found"},
                    )

                stmt = (
                    select(CrewAgentModel, AgentModel)
                    .join(AgentModel, CrewAgentModel.agent_id == AgentModel.id)
                    .where(CrewAgentModel.crew_id == crew_id)
                    .order_by(CrewAgentModel.order_index)
                )
                result = await session.execute(stmt)
                rows = result.all()

                if not rows:
                    return NodeResult(
                        node_id=node.id,
                        status=NodeStatus.FAILED,
                        error={"message": f"Crew '{crew_id}' has no agents"},
                    )

                workers = []
                manager = None

                for ca, agent_model in rows:
                    agent_config = AgentConfig(
                        name=agent_model.name,
                        role=agent_model.role or "",
                        goal=agent_model.goal or "",
                        backstory=agent_model.backstory or "",
                        system_prompt=agent_model.system_prompt or "",
                        provider=agent_model.llm_settings.get(
                            "provider", settings.DEFAULT_LLM_PROVIDER
                        ),
                        model=agent_model.llm_settings.get(
                            "model", settings.DEFAULT_LLM_MODEL
                        ),
                        temperature=agent_model.llm_settings.get(
                            "temperature", settings.DEFAULT_LLM_TEMPERATURE
                        ),
                        max_tokens=agent_model.llm_settings.get(
                            "max_tokens", settings.DEFAULT_LLM_MAX_TOKENS
                        ),
                        max_iterations=agent_model.max_iterations
                        or settings.DEFAULT_MAX_ITERATIONS,
                        tools=agent_model.tools or [],
                    )

                    llm_client = self._create_llm_client(agent_model.llm_settings)

                    base_agent = BaseAgent(
                        config=agent_config,
                        llm_client=llm_client,
                        tool_registry=self.tool_registry,
                    )

                    if ca.role_in_crew == "manager":
                        manager = base_agent
                    else:
                        workers.append(base_agent)

                if not manager and workers:
                    manager = workers.pop(0)

                if not manager:
                    return NodeResult(
                        node_id=node.id,
                        status=NodeStatus.FAILED,
                        error={"message": f"Crew '{crew_id}' has no valid agents"},
                    )

                crew_config = CrewConfig(
                    mode=CrewMode(crew_record.mode or "hierarchical"),
                    max_workers=crew_record.config.get("max_workers", 5),
                    shared_context_enabled=crew_record.config.get(
                        "shared_context_enabled", True
                    ),
                    auto_delegate=crew_record.config.get("auto_delegate", True),
                )

                crew = Crew(
                    manager=manager,
                    workers=workers,
                    config=crew_config,
                    event_bus=self.event_bus,
                    crew_id=str(crew_id),
                )

                crew_result = await crew.execute(
                    task_description=task_description,
                    context={
                        "run_id": run_id,
                        "node_id": node.id,
                        "tenant_id": state.env_vars.get("tenant_id"),
                        "user_id": state.env_vars.get("user_id"),
                    },
                )

                output_key = config.get("output_key", node.id)
                state.run_vars[output_key] = crew_result.output

                return NodeResult(
                    node_id=node.id,
                    status=NodeStatus.SUCCEEDED,
                    output={
                        "output": crew_result.output,
                        "manager_reasoning": crew_result.manager_reasoning,
                        "worker_results": [
                            {
                                "worker_name": w.worker_name,
                                "output": w.output,
                                "success": w.success,
                                "error": w.error,
                            }
                            for w in crew_result.worker_results
                        ],
                        "tool_calls": crew_result.tool_calls,
                    },
                )

        except Exception as e:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"type": type(e).__name__, "message": str(e)},
            )

    def _create_llm_client(self, llm_settings: dict[str, Any]) -> LLMClient:
        return create_llm_client(llm_settings)

"""Crew 执行服务.

将 crews.py 路由层中的业务逻辑（Agent 加载、LLMClient 构建、Crew 执行、
结果处理）提取到 Service 层，保持路由层只负责参数校验和响应封装。

Phase 10: 多 Agent 协作增强
"""

from __future__ import annotations

import asyncio
import os
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.agent.base import AgentConfig, BaseAgent
from nexus.agent.crew import Crew, CrewConfig, CrewMode
from nexus.agent.llm_client import LLMClient
from nexus.config import settings
from nexus.models.agent import Agent as AgentModel
from nexus.services.crew import CrewRunService, CrewService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_llm_client(model_config: dict) -> LLMClient:
    """根据模型配置创建 LLMClient.

    FIXME(P1): 将 provider_base_urls 移到 nexus/config.py 的 Settings 中，
    支持通过环境变量覆盖 Provider 配置。
    """
    provider = model_config.get("provider", settings.DEFAULT_LLM_PROVIDER)

    provider_base_urls = {
        "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
        "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
        "siliconflow": ("https://api.siliconflow.cn/v1", "SILICONFLOW_API_KEY"),
        "dashscope": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
        "zhipu": ("https://open.bigmodel.cn/api/paas/v4", "ZHIPU_API_KEY"),
    }

    if provider in provider_base_urls:
        direct_url, env_key = provider_base_urls[provider]
        api_key = os.environ.get(env_key)
        if api_key:
            base_url = direct_url
        else:
            base_url = settings.LITELLM_PROXY_URL
            api_key = settings.LITELLM_API_KEY
    else:
        base_url = settings.LITELLM_PROXY_URL
        api_key = settings.LITELLM_API_KEY

    return LLMClient(proxy_url=base_url, api_key=api_key)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class CrewExecutionService:
    """Crew 执行服务.

    负责 Crew 执行的完整生命周期：
    1. 加载 Crew 配置和关联 Agent
    2. 创建执行记录
    3. 构建 BaseAgent 实例和 LLMClient
    4. 执行 Crew 协作任务
    5. 更新执行记录状态

    所有数据库操作使用传入的 session，由调用方管理事务边界（commit/rollback）。
    """

    def __init__(self):
        self.crew_service = CrewService()
        self.crew_run_service = CrewRunService()

    async def run(
        self,
        session: AsyncSession,
        crew_id: UUID,
        tenant_id: UUID,
        task_description: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """执行 Crew 并返回结果.

        Args:
            session: 数据库会话（由调用方管理事务）
            crew_id: Crew ID
            tenant_id: 租户 ID
            task_description: 任务描述
            context: 额外上下文

        Returns:
            包含 run_id, status, output, worker_results, duration_ms 的字典

        Raises:
            ValueError: Crew 不存在或无有效 Agent
            Exception: Crew 执行失败
        """
        # 1. 加载 Crew 配置
        crew_data = await self.crew_service.get_with_agents(session, crew_id, tenant_id)
        if not crew_data:
            raise ValueError("Crew not found")

        # 2. 创建执行记录（flush 使其获得 ID，但不 commit）
        crew_run = await self.crew_run_service.create(
            session, crew_id, task_description, tenant_id
        )
        await session.flush()

        # 3. 构建 Agent 实例（使用同一个 session）
        manager, workers = await self._build_agents(session, crew_data)

        if not manager:
            raise ValueError("Crew has no valid agents")

        # Sequential / Parallel 模式下 manager 也应参与执行
        if crew_data["mode"] in ("sequential", "parallel") and manager not in workers:
            workers.append(manager)

        # 4. 构建 Crew 配置并执行
        config = CrewConfig(
            mode=CrewMode(crew_data["mode"]),
            max_workers=crew_data.get("config", {}).get("max_workers", 5),
            shared_context_enabled=crew_data.get("config", {}).get(
                "shared_context_enabled", True
            ),
            auto_delegate=crew_data.get("config", {}).get("auto_delegate", True),
        )

        crew = Crew(
            manager=manager,
            workers=workers,
            config=config,
            crew_id=str(crew_id),
        )

        start = perf_counter()
        try:
            result = await crew.execute(
                task_description=task_description,
                context=context,
            )
            duration_ms = int((perf_counter() - start) * 1000)

            # 5. 更新执行记录（completed）
            worker_results = [
                {
                    "worker_name": w.worker_name,
                    "output": w.output,
                    "success": w.success,
                    "error": w.error,
                }
                for w in result.worker_results
            ]

            await self.crew_run_service.update_status(
                session,
                crew_run.id,
                status="completed",
                output=result.output,
                worker_results=worker_results,
                duration_ms=duration_ms,
            )

            return {
                "run_id": str(crew_run.id),
                "status": "completed",
                "output": result.output,
                "worker_results": worker_results,
                "duration_ms": duration_ms,
            }

        except Exception as exc:
            duration_ms = int((perf_counter() - start) * 1000)

            # 更新执行记录（failed）
            await self.crew_run_service.update_status(
                session,
                crew_run.id,
                status="failed",
                output="",
                worker_results=[{"error": str(exc)}],
                duration_ms=duration_ms,
            )

            raise

    async def _build_agents(
        self,
        session: AsyncSession,
        crew_data: dict[str, Any],
    ) -> tuple[BaseAgent | None, list[BaseAgent]]:
        """根据 Crew 数据构建 Agent 实例.

        Args:
            session: 数据库会话
            crew_data: get_with_agents 返回的 Crew 数据

        Returns:
            (manager_agent, worker_agents_list)
        """
        workers: list[BaseAgent] = []
        manager: BaseAgent | None = None

        for agent_ref in crew_data.get("agents", []):
            agent_model = await session.get(AgentModel, UUID(agent_ref["id"]))
            if not agent_model:
                continue

            agent_config = AgentConfig(
                name=agent_model.name,
                role=agent_model.role or "",
                goal=agent_model.goal or "",
                backstory=agent_model.backstory or "",
                system_prompt=agent_model.system_prompt or "",
                provider=agent_model.model_config.get(
                    "provider", settings.DEFAULT_LLM_PROVIDER
                ),
                model=agent_model.model_config.get(
                    "model", settings.DEFAULT_LLM_MODEL
                ),
                temperature=agent_model.model_config.get(
                    "temperature", settings.DEFAULT_LLM_TEMPERATURE
                ),
                max_tokens=agent_model.model_config.get(
                    "max_tokens", settings.DEFAULT_LLM_MAX_TOKENS
                ),
                max_iterations=agent_model.max_iterations
                or settings.DEFAULT_MAX_ITERATIONS,
                tools=agent_model.tools or [],
            )

            llm_client = _create_llm_client(agent_model.model_config)
            base_agent = BaseAgent(
                config=agent_config,
                llm_client=llm_client,
            )

            if agent_ref.get("role_in_crew") == "manager":
                manager = base_agent
            else:
                workers.append(base_agent)

        if not manager and workers:
            manager = workers[0]

        return manager, workers

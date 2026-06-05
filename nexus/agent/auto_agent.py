"""AutoAgent — autonomous goal-to-execution pipeline."""
import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from nexus.agent.planner import GoalDecomposer, WorkflowBuilder, Plan, WorkflowBlueprint

logger = logging.getLogger(__name__)


@dataclass
class AutoAgentResult:
    """AutoAgent 执行结果."""
    goal: str
    plan: Plan
    blueprint: WorkflowBlueprint
    success: bool = True
    error: str = ""


class AutoAgent:
    """自动Agent — 从目标描述到可执行 DAG 的全自动流水线.

    Usage:
        agent = AutoAgent(llm_client)
        result = await agent.plan_async("分析销售数据并生成周报")
        # result.blueprint.workflow_config 可直接用于创建 Workflow

        # Or use the sync wrapper:
        result = agent.plan("summarize this document")
    """

    def __init__(self, llm_client=None):
        self.decomposer = GoalDecomposer(llm_client=llm_client)
        self.builder = WorkflowBuilder()

    def plan(self, goal: str) -> AutoAgentResult:
        """同步包装 — 从目标生成可执行计划.

        在无 LLM 调用的规则兜底路径下可直接同步返回；
        适合测试场景和简单目标。
        """
        try:
            # 规则兜底路径：检查 simple patterns / default plan
            for pattern in self.decomposer.SIMPLE_PATTERNS:
                if pattern in goal.lower():
                    plan = self.decomposer._simple_plan(
                        goal, self.decomposer.SIMPLE_PATTERNS[pattern]
                    )
                    blueprint = self.builder.build(plan)
                    return AutoAgentResult(
                        goal=goal,
                        plan=plan,
                        blueprint=blueprint,
                    )
            # 无 LLM 时的默认分解
            plan = self.decomposer._default_plan(goal)
            blueprint = self.builder.build(plan)
            return AutoAgentResult(
                goal=goal,
                plan=plan,
                blueprint=blueprint,
            )
        except Exception as e:
            logger.error(f"AutoAgent planning failed: {e}")
            return AutoAgentResult(
                goal=goal,
                plan=Plan(goal=goal, subtasks=[]),
                blueprint=WorkflowBlueprint(
                    plan=Plan(goal=goal, subtasks=[]),
                    workflow_config={"nodes": [], "edges": []},
                    agent_configs=[],
                ),
                success=False,
                error=str(e),
            )

    async def plan_async(self, goal: str) -> AutoAgentResult:
        """异步 — 从目标生成可执行计划 (支持 LLM 分解)."""
        try:
            plan = await self.decomposer.decompose(goal)
            blueprint = self.builder.build(plan)
            return AutoAgentResult(
                goal=goal,
                plan=plan,
                blueprint=blueprint,
            )
        except Exception as e:
            logger.error(f"AutoAgent planning failed: {e}")
            return AutoAgentResult(
                goal=goal,
                plan=plan,
                blueprint=WorkflowBlueprint(
                    plan=Plan(goal=goal, subtasks=[]),
                    workflow_config={"nodes": [], "edges": []},
                    agent_configs=[],
                ),
                success=False,
                error=str(e),
            )

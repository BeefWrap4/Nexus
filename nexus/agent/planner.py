"""Goal Decomposer — LLM-powered task decomposition into executable DAGs."""
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Subtask:
    """子任务定义."""
    id: str
    name: str
    description: str
    tool_needs: list[str] = field(default_factory=list)  # 需要的工具
    depends_on: list[str] = field(default_factory=list)   # 依赖的子任务ID
    agent_role: str = ""        # 执行此任务的 Agent 角色
    agent_goal: str = ""        # Agent 目标
    expected_output: str = ""   # 期望输出


@dataclass
class Plan:
    """分解计划."""
    goal: str
    subtasks: list[Subtask]
    reasoning: str = ""         # LLM 分解推理


@dataclass
class WorkflowBlueprint:
    """可执行的 DAG 蓝图."""
    plan: Plan
    workflow_config: dict[str, Any]     # WorkflowDefinition config
    agent_configs: list[dict[str, Any]]  # 每个节点的 Agent 配置


class GoalDecomposer:
    """目标分解器 — 将高层目标分解为可执行 DAG.

    使用 LLM 进行任务分解和依赖推理，输出结构化的 WorkflowDefinition。
    支持规则兜底（简单目标不经过 LLM）。
    """

    # 简单目标 → 直接映射（规则兜底，不消耗 LLM 调用）
    SIMPLE_PATTERNS: dict[str, list[str]] = {
        "hello": ["greet"],
        "summarize": ["read", "summarize", "output"],
        "translate": ["parse", "translate", "output"],
    }

    def __init__(self, llm_client=None):
        self.llm = llm_client

    async def decompose(self, goal: str) -> Plan:
        """分解目标为子任务列表."""
        # 简单目标走规则兜底
        for pattern, steps in self.SIMPLE_PATTERNS.items():
            if pattern in goal.lower():
                return self._simple_plan(goal, steps)

        # 使用 LLM 分解
        if self.llm:
            return await self._llm_decompose(goal)

        # 无 LLM 时的默认分解
        return self._default_plan(goal)

    def _simple_plan(self, goal: str, steps: list[str]) -> Plan:
        """简单目标规则兜底."""
        subtasks = []
        prev_id = None
        for i, step in enumerate(steps):
            task_id = f"task_{i+1}"
            subtask = Subtask(
                id=task_id,
                name=step.capitalize(),
                description=f"Execute {step} step for: {goal}",
                depends_on=[prev_id] if prev_id else [],
            )
            subtasks.append(subtask)
            prev_id = task_id

        return Plan(goal=goal, subtasks=subtasks, reasoning="Simple pattern match")

    def _default_plan(self, goal: str) -> Plan:
        """无 LLM 时的默认分解."""
        return Plan(
            goal=goal,
            subtasks=[
                Subtask(id="task_1", name="Analyze", description=f"Analyze: {goal}"),
                Subtask(id="task_2", name="Execute", description="Execute the plan",
                        depends_on=["task_1"]),
                Subtask(id="task_3", name="Summarize", description="Summarize results",
                        depends_on=["task_2"]),
            ],
            reasoning="Default sequential decomposition",
        )

    async def _llm_decompose(self, goal: str) -> Plan:
        """使用 LLM 分解目标."""
        prompt = f"""Break down the following goal into subtasks for a multi-agent workflow.
Return a JSON array of subtasks. Each subtask must have:
- id: unique string
- name: short task name
- description: what this task does
- depends_on: list of task IDs this depends on (empty if no dependencies)
- tool_needs: list of tool names needed (empty if none)
- agent_role: the role of the agent that should execute this

Goal: {goal}

Return ONLY valid JSON array, no other text.
Example: [{{"id":"1","name":"Fetch Data","description":"...","depends_on":[],"tool_needs":["http_request"],"agent_role":"Data Fetcher"}}]"""

        response = await self.llm.call(
            system_prompt="You are a workflow planner. Output only valid JSON.",
            user_prompt=prompt,
        )

        try:
            tasks_data = json.loads(response.get("content", "[]"))
        except json.JSONDecodeError:
            # Fallback: try to extract JSON from response
            match = re.search(r'\[.*\]', response.get("content", ""), re.DOTALL)
            tasks_data = json.loads(match.group()) if match else []

        subtasks = [
            Subtask(
                id=t.get("id", f"task_{i}"),
                name=t.get("name", f"Task {i}"),
                description=t.get("description", ""),
                tool_needs=t.get("tool_needs", []),
                depends_on=t.get("depends_on", []),
                agent_role=t.get("agent_role", ""),
            )
            for i, t in enumerate(tasks_data)
        ]

        return Plan(goal=goal, subtasks=subtasks, reasoning="LLM decomposition")


class WorkflowBuilder:
    """将 Plan 转换为可执行的 WorkflowDefinition."""

    def build(self, plan: Plan) -> WorkflowBlueprint:
        """从 Plan 构建 WorkflowBlueprint."""
        nodes = []
        edges = []
        agent_configs = []

        # Start node
        nodes.append({"id": "start", "type": "start"})

        # Task nodes
        for task in plan.subtasks:
            node_id = f"agent_{task.id}"
            nodes.append({
                "id": node_id,
                "type": "agent",
                "config": {
                    "agent_ref": task.name.replace(" ", "_"),
                    "system_prompt": f"Role: {task.agent_role or 'Executor'}. Task: {task.description}",
                },
            })

            agent_configs.append({
                "name": task.name.replace(" ", "_"),
                "role": task.agent_role or task.name,
                "goal": task.description,
                "backstory": f"Executing subtask: {task.name}",
                "tools": task.tool_needs,
            })

            # Edges: depends_on → this node
            if task.depends_on:
                for dep_id in task.depends_on:
                    edges.append({
                        "source": f"agent_{dep_id}",
                        "target": node_id,
                    })
            else:
                edges.append({"source": "start", "target": node_id})

        # End node
        end_id = "end"
        nodes.append({"id": end_id, "type": "end"})

        # Connect leaf nodes to end
        leaf_ids = {f"agent_{t.id}" for t in plan.subtasks}
        target_ids = {e["source"] for e in edges}
        for leaf in leaf_ids - target_ids:
            edges.append({"source": leaf, "target": end_id})

        # Ensure nodes with no outgoing edges still connect to end
        for t in plan.subtasks:
            nid = f"agent_{t.id}"
            if not any(e["source"] == nid for e in edges):
                edges.append({"source": nid, "target": end_id})

        workflow_config = {
            "nodes": nodes,
            "edges": edges,
        }

        return WorkflowBlueprint(
            plan=plan,
            workflow_config=workflow_config,
            agent_configs=agent_configs,
        )

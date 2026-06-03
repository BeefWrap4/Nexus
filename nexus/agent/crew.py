"""多 Agent 协作编排器 — Crew Manager-Worker 模式.

设计来源:
- CrewAI: Manager-Worker 任务分解与分配
- AutoGen: Agent 间消息传递
- LangGraph: 状态机驱动协作

核心概念:
- Crew: 一组 Agent 的协作单元
- Manager: 负责任务分解和 Worker 分配
- Worker: 负责执行具体子任务
- CrewTask: 子任务定义
- CrewResult: 协作结果聚合

使用示例:
    crew = Crew(
        manager=BaseAgent(config=manager_config, tool_registry=registry),
        workers=[
            BaseAgent(config=worker_config_1, tool_registry=registry),
            BaseAgent(config=worker_config_2, tool_registry=registry),
        ],
    )
    result = await crew.execute("分析这份财报并生成摘要")
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from nexus.agent.base import AgentConfig, BaseAgent, Task


@dataclass
class CrewTask:
    """Crew 子任务."""

    description: str
    assigned_to: str = ""  # Worker agent name
    expected_output: str = ""
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class CrewWorkerResult:
    """Worker 执行结果."""

    worker_name: str
    task: CrewTask
    output: str = ""
    reasoning: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    success: bool = True
    error: str = ""


@dataclass
class CrewResult:
    """Crew 协作最终结果."""

    output: str
    manager_reasoning: str = ""
    worker_results: list[CrewWorkerResult] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)


class Crew:
    """多 Agent 协作编排器（Manager-Worker 模式）.

    执行流程:
    1. Manager 接收主任务，分解为子任务列表
    2. 根据子任务特征分配给合适的 Worker
    3. Workers 并行执行子任务
    4. Manager 聚合所有 Worker 结果，生成最终输出
    """

    def __init__(
        self,
        manager: BaseAgent,
        workers: list[BaseAgent],
        max_workers: int = 5,
    ):
        self.manager = manager
        self.workers = {w.config.name: w for w in workers}
        self.max_workers = max_workers

    async def execute(
        self,
        task_description: str,
        context: dict[str, Any] | None = None,
    ) -> CrewResult:
        """执行 Crew 协作任务.

        Args:
            task_description: 主任务描述
            context: 额外上下文

        Returns:
            CrewResult: 协作结果
        """
        ctx = context or {}

        # 1. Manager 分解任务
        sub_tasks = await self._delegate(task_description, ctx)

        # 2. Workers 并行执行（限制并发数）
        semaphore = asyncio.Semaphore(self.max_workers)

        async def run_with_limit(task: CrewTask) -> CrewWorkerResult:
            async with semaphore:
                return await self._run_worker(task, ctx)

        worker_results = await asyncio.gather(
            *[run_with_limit(t) for t in sub_tasks],
            return_exceptions=True,
        )

        # 3. 处理异常结果
        processed_results: list[CrewWorkerResult] = []
        for result in worker_results:
            if isinstance(result, Exception):
                processed_results.append(
                    CrewWorkerResult(
                        worker_name="unknown",
                        task=CrewTask(description="", assigned_to=""),
                        success=False,
                        error=str(result),
                    )
                )
            else:
                processed_results.append(result)

        # 4. Manager 聚合结果
        final_output = await self._aggregate(
            task_description, processed_results, ctx
        )

        # 收集所有 tool_calls
        all_tool_calls = []
        for r in processed_results:
            all_tool_calls.extend(r.tool_calls)

        return CrewResult(
            output=final_output.output,
            manager_reasoning=final_output.reasoning,
            worker_results=processed_results,
            tool_calls=all_tool_calls,
        )

    async def _delegate(
        self,
        task_description: str,
        context: dict[str, Any],
    ) -> list[CrewTask]:
        """Manager 分解任务为子任务列表.

        Manager 使用自身的 ReAct 能力分析任务，返回结构化的子任务列表。
        如果 Manager 无法分解（fallback），返回单个包含原任务的子任务。
        """
        delegation_prompt = (
            f"You are a task delegation manager. Break down the following task "
            f"into {len(self.workers)} or fewer sub-tasks that can be executed in parallel.\n\n"
            f"Main task: {task_description}\n\n"
            f"Available workers: {', '.join(self.workers.keys())}\n\n"
            f"Respond with a JSON array of sub-tasks, each with 'description' and 'assigned_to' fields.\n"
            f"Example: [{'{'}'description': 'Research topic', 'assigned_to': 'researcher'{'}'}]"
        )

        try:
            from nexus.agent.llm_client import LLMClient

            llm = self.manager.llm_client or LLMClient()
            response = await llm.call(
                system_prompt="You are a task decomposition expert.",
                user_prompt=delegation_prompt,
                model=self.manager.config.model,
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            # 解析 JSON 响应
            import json

            content = response.content.strip()
            # 尝试提取 JSON 数组
            try:
                tasks_data = json.loads(content)
                if isinstance(tasks_data, dict) and "tasks" in tasks_data:
                    tasks_data = tasks_data["tasks"]
                if not isinstance(tasks_data, list):
                    tasks_data = [tasks_data]
            except json.JSONDecodeError:
                # Fallback: 返回单个任务
                tasks_data = [{"description": task_description, "assigned_to": ""}]

            sub_tasks = []
            for t in tasks_data:
                if isinstance(t, dict):
                    sub_tasks.append(
                        CrewTask(
                            description=t.get("description", ""),
                            assigned_to=t.get("assigned_to", ""),
                            expected_output=t.get("expected_output", ""),
                        )
                    )

            # 过滤空任务
            sub_tasks = [t for t in sub_tasks if t.description]

            # 如果没有有效子任务，fallback 到单个任务
            if not sub_tasks:
                sub_tasks = [CrewTask(description=task_description, assigned_to="")]

            return sub_tasks

        except Exception:
            # 任何错误都 fallback 到单个任务
            return [CrewTask(description=task_description, assigned_to="")]

    async def _run_worker(
        self,
        task: CrewTask,
        context: dict[str, Any],
    ) -> CrewWorkerResult:
        """执行 Worker 子任务.

        根据 assigned_to 找到对应 Worker，委托执行。
        如果指定的 Worker 不存在，使用第一个可用 Worker。
        """
        worker_name = task.assigned_to
        worker = self.workers.get(worker_name)

        if not worker:
            # 未指定或找不到，使用第一个 Worker
            if self.workers:
                worker_name, worker = next(iter(self.workers.items()))
            else:
                return CrewWorkerResult(
                    worker_name="none",
                    task=task,
                    success=False,
                    error="No workers available",
                )

        try:
            result = await worker.execute(
                Task(
                    description=task.description,
                    expected_output=task.expected_output,
                    context=task.context,
                ),
                context=context,
            )
            return CrewWorkerResult(
                worker_name=worker_name,
                task=task,
                output=result.output,
                reasoning=result.reasoning,
                tool_calls=result.tool_calls,
                success=result.status == "success",
            )
        except Exception as e:
            return CrewWorkerResult(
                worker_name=worker_name,
                task=task,
                success=False,
                error=str(e),
            )

    async def _aggregate(
        self,
        original_task: str,
        worker_results: list[CrewWorkerResult],
        context: dict[str, Any],
    ) -> CrewWorkerResult:
        """Manager 聚合所有 Worker 结果.

        将多个 Worker 的输出合并为统一的最终答案。
        """
        # 构建聚合上下文
        worker_outputs = []
        for r in worker_results:
            if r.success:
                worker_outputs.append(
                    f"[{r.worker_name}] {r.task.description}:\n{r.output}"
                )
            else:
                worker_outputs.append(
                    f"[{r.worker_name}] {r.task.description}:\nERROR: {r.error}"
                )

        aggregation_prompt = (
            f"Synthesize the following worker outputs into a final answer "
            f"for the original task: {original_task}\n\n"
            f"Worker outputs:\n"
            + "\n\n---\n\n".join(worker_outputs)
        )

        try:
            result = await self.manager.execute(
                Task(
                    description=aggregation_prompt,
                    expected_output="A comprehensive final answer.",
                ),
                context=context,
            )
            return CrewWorkerResult(
                worker_name=self.manager.config.name,
                task=CrewTask(description=original_task),
                output=result.output,
                reasoning=result.reasoning,
                tool_calls=result.tool_calls,
                success=True,
            )
        except Exception as e:
            # Fallback: 简单拼接
            combined = "\n\n".join(
                f"## {r.worker_name}\n{r.output}" for r in worker_results if r.success
            )
            return CrewWorkerResult(
                worker_name=self.manager.config.name,
                task=CrewTask(description=original_task),
                output=combined or f"Aggregation failed: {e}",
                success=True,
            )

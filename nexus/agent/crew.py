"""多 Agent 协作编排器 — Crew Manager-Worker 模式.

Phase 10 增强:
- 三种协作模式: Hierarchical | Sequential | Parallel
- Agent 间共享上下文 (shared_context)
- EventBus 实时事件广播
- Crew Memory 共享

设计来源:
- CrewAI: Manager-Worker 任务分解与分配
- AutoGen: Agent 间消息传递
- LangGraph: 状态机驱动协作

核心概念:
- Crew: 一组 Agent 的协作单元
- Manager: 负责任务分解和 Worker 分配 (Hierarchical 模式)
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
        config=CrewConfig(mode=CrewMode.HIERARCHICAL),
        event_bus=event_bus,
    )
    result = await crew.execute("分析这份财报并生成摘要")
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from nexus.agent.base import AgentConfig, BaseAgent, Task

logger = logging.getLogger(__name__)


class CrewMode(str, Enum):
    """Crew 协作模式."""

    HIERARCHICAL = "hierarchical"
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


@dataclass
class CrewConfig:
    """Crew 配置."""

    mode: CrewMode = CrewMode.HIERARCHICAL
    max_workers: int = 5
    shared_context_enabled: bool = True
    auto_delegate: bool = True  # Manager 自动分解任务
    max_shared_context_size: int = 100_000  # 最大共享上下文大小 (bytes)


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
    shared_context: dict[str, Any] = field(default_factory=dict)


class Crew:
    """多 Agent 协作编排器（支持三种协作模式）.

    执行流程:
    1. Hierarchical: Manager 接收主任务 → 分解为子任务 → Workers 并行执行
                     → Manager 聚合所有结果生成最终输出
    2. Sequential: Workers 按顺序执行，每个 Worker 的输出作为下一个 Worker 的上下文
    3. Parallel: Workers 并行执行，无依赖关系，结果各自写入 shared_context

    所有模式下均支持:
    - shared_context: Agent 间共享状态
    - EventBus 实时事件广播
    - 优雅降级（Worker 失败不影响整体）
    """

    def __init__(
        self,
        manager: BaseAgent | None = None,
        workers: list[BaseAgent] | None = None,
        config: CrewConfig | None = None,
        event_bus: Any = None,
        crew_id: str = "",
    ):
        self.manager = manager
        self.workers = {w.config.name: w for w in (workers or [])}
        self.config = config or CrewConfig()
        self.event_bus = event_bus
        self.crew_id = crew_id or ""
        self.shared_context: dict[str, Any] = {
            "crew_id": self.crew_id,
            "mode": self.config.mode.value,
            "worker_outputs": {},
        }

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
        start_time = asyncio.get_event_loop().time()

        # 初始化 shared_context
        if self.config.shared_context_enabled:
            self.shared_context.update({
                "task_description": task_description,
                "original_context": ctx,
            })

        await self._publish_event(
            step="crew_started",
            data={"task": task_description, "mode": self.config.mode.value},
        )

        # 根据模式选择执行策略
        if self.config.mode == CrewMode.HIERARCHICAL:
            result = await self._execute_hierarchical(task_description, ctx)
        elif self.config.mode == CrewMode.SEQUENTIAL:
            result = await self._execute_sequential(task_description, ctx)
        else:  # PARALLEL
            result = await self._execute_parallel(task_description, ctx)

        duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
        result.shared_context = dict(self.shared_context)

        await self._publish_event(
            step="crew_complete",
            data={
                "duration_ms": duration_ms,
                "output_preview": result.output[:200] if result.output else "",
                "worker_count": len(result.worker_results),
            },
        )

        return result

    # ------------------------------------------------------------------
    # Hierarchical 模式
    # ------------------------------------------------------------------

    async def _execute_hierarchical(
        self,
        task_description: str,
        context: dict[str, Any],
    ) -> CrewResult:
        """层级模式: Manager 分解 → Workers 并行 → Manager 聚合."""
        if not self.manager:
            # 无 Manager 时 fallback 到 Parallel 模式
            return await self._execute_parallel(task_description, context)

        # 1. Manager 分解任务
        await self._publish_event(step="delegate_start", data={})
        sub_tasks = await self._delegate(task_description, context)
        await self._publish_event(
            step="delegate_complete",
            data={"task_count": len(sub_tasks), "tasks": [t.description for t in sub_tasks]},
        )

        # 2. Workers 并行执行
        worker_results = await self._run_workers_parallel(sub_tasks, context)

        # 3. Manager 聚合结果
        await self._publish_event(step="aggregate_start", data={})
        final = await self._aggregate(task_description, worker_results, context)
        await self._publish_event(step="aggregate_complete", data={})

        all_tool_calls = []
        for r in worker_results:
            all_tool_calls.extend(r.tool_calls)

        return CrewResult(
            output=final.output,
            manager_reasoning=final.reasoning,
            worker_results=worker_results,
            tool_calls=all_tool_calls,
        )

    # ------------------------------------------------------------------
    # Sequential 模式
    # ------------------------------------------------------------------

    async def _execute_sequential(
        self,
        task_description: str,
        context: dict[str, Any],
    ) -> CrewResult:
        """顺序模式: Workers 按顺序执行，输出传递为上下文."""
        worker_results: list[CrewWorkerResult] = []

        # 获取按 order_index 排序的 workers（若无 order，按 workers dict 顺序）
        sorted_workers = list(self.workers.items())

        await self._publish_event(
            step="sequential_start",
            data={"worker_count": len(sorted_workers)},
        )

        for idx, (worker_name, worker) in enumerate(sorted_workers):
            await self._publish_event(
                step="worker_start",
                data={"worker": worker_name, "index": idx},
            )

            # 构建任务描述：包含原始任务 + 前一个 worker 的输出
            task_desc = self._build_sequential_task(
                task_description, worker_name, worker_results
            )

            task = CrewTask(
                description=task_desc,
                assigned_to=worker_name,
                context=dict(self.shared_context) if self.config.shared_context_enabled else {},
            )

            result = await self._run_worker(task, context)
            worker_results.append(result)

            # 写入 shared_context
            if self.config.shared_context_enabled:
                self.shared_context["worker_outputs"][worker_name] = {
                    "output": result.output,
                    "success": result.success,
                    "error": result.error,
                }
                self._trim_shared_context()

            await self._publish_event(
                step="worker_complete",
                data={
                    "worker": worker_name,
                    "success": result.success,
                    "output_preview": result.output[:200] if result.output else "",
                },
            )

        # 聚合：最后一个 worker 的输出，或 Manager 聚合（如果有 Manager）
        final_output = ""
        final_reasoning = ""

        if self.manager and len(worker_results) > 0:
            final = await self._aggregate(task_description, worker_results, context)
            final_output = final.output
            final_reasoning = final.reasoning
        elif worker_results:
            # 无 Manager 时，简单拼接所有 worker 输出
            final_output = "\n\n".join(
                f"## {r.worker_name}\n{r.output}" for r in worker_results if r.success
            )

        all_tool_calls = []
        for r in worker_results:
            all_tool_calls.extend(r.tool_calls)

        await self._publish_event(step="sequential_complete", data={})

        return CrewResult(
            output=final_output,
            manager_reasoning=final_reasoning,
            worker_results=worker_results,
            tool_calls=all_tool_calls,
        )

    def _build_sequential_task(
        self,
        original_task: str,
        current_worker_name: str,
        previous_results: list[CrewWorkerResult],
    ) -> str:
        """构建 Sequential 模式下当前 Worker 的任务描述."""
        parts = [f"Original task: {original_task}"]

        if previous_results:
            parts.append("\nPrevious worker outputs:")
            for r in previous_results:
                if r.success:
                    parts.append(f"\n[{r.worker_name}] {r.task.description}:\n{r.output}")
                else:
                    parts.append(f"\n[{r.worker_name}] ERROR: {r.error}")

        parts.append(f"\nYour turn ({current_worker_name}). Continue the task based on previous outputs.")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Parallel 模式
    # ------------------------------------------------------------------

    async def _execute_parallel(
        self,
        task_description: str,
        context: dict[str, Any],
    ) -> CrewResult:
        """并行模式: Workers 并行执行，无依赖关系."""
        await self._publish_event(
            step="parallel_start",
            data={"worker_count": len(self.workers)},
        )

        # 为每个 worker 创建相同的任务
        sub_tasks = [
            CrewTask(
                description=task_description,
                assigned_to=name,
                context=dict(self.shared_context) if self.config.shared_context_enabled else {},
            )
            for name in self.workers.keys()
        ]

        worker_results = await self._run_workers_parallel(sub_tasks, context)

        # 写入 shared_context
        if self.config.shared_context_enabled:
            for r in worker_results:
                self.shared_context["worker_outputs"][r.worker_name] = {
                    "output": r.output,
                    "success": r.success,
                    "error": r.error,
                }
            self._trim_shared_context()

        # 聚合
        final_output = ""
        final_reasoning = ""

        if self.manager and len(worker_results) > 0:
            final = await self._aggregate(task_description, worker_results, context)
            final_output = final.output
            final_reasoning = final.reasoning
        elif worker_results:
            final_output = "\n\n".join(
                f"## {r.worker_name}\n{r.output}" for r in worker_results if r.success
            )

        all_tool_calls = []
        for r in worker_results:
            all_tool_calls.extend(r.tool_calls)

        await self._publish_event(step="parallel_complete", data={})

        return CrewResult(
            output=final_output,
            manager_reasoning=final_reasoning,
            worker_results=worker_results,
            tool_calls=all_tool_calls,
        )

    # ------------------------------------------------------------------
    # Worker 执行（通用）
    # ------------------------------------------------------------------

    async def _run_workers_parallel(
        self,
        sub_tasks: list[CrewTask],
        context: dict[str, Any],
    ) -> list[CrewWorkerResult]:
        """并行执行多个 Worker（带并发限制）."""
        semaphore = asyncio.Semaphore(self.config.max_workers)

        async def run_with_limit(task: CrewTask) -> CrewWorkerResult:
            async with semaphore:
                return await self._run_worker(task, context)

        results = await asyncio.gather(
            *[run_with_limit(t) for t in sub_tasks],
            return_exceptions=True,
        )

        processed: list[CrewWorkerResult] = []
        for result in results:
            if isinstance(result, Exception):
                processed.append(
                    CrewWorkerResult(
                        worker_name="unknown",
                        task=CrewTask(description="", assigned_to=""),
                        success=False,
                        error=str(result),
                    )
                )
            else:
                processed.append(result)

        return processed

    async def _run_worker(
        self,
        task: CrewTask,
        context: dict[str, Any],
    ) -> CrewWorkerResult:
        """执行单个 Worker 子任务."""
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
            # 构建 Task，注入 shared_context
            task_context = dict(context)
            if self.config.shared_context_enabled and self.shared_context:
                task_context["shared_context"] = dict(self.shared_context)

            result = await worker.execute(
                Task(
                    description=task.description,
                    expected_output=task.expected_output,
                    context=task.context,
                ),
                context=task_context,
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

    # ------------------------------------------------------------------
    # Manager 任务分解
    # ------------------------------------------------------------------

    async def _delegate(
        self,
        task_description: str,
        context: dict[str, Any],
    ) -> list[CrewTask]:
        """Manager 分解任务为子任务列表.

        Manager 使用自身的 ReAct 能力分析任务，返回结构化的子任务列表。
        如果 Manager 无法分解（fallback），返回单个包含原任务的子任务。
        """
        if not self.manager or not self.config.auto_delegate:
            # 无 Manager 或关闭自动分解：为每个 Worker 分配相同任务
            return [
                CrewTask(description=task_description, assigned_to=name)
                for name in self.workers.keys()
            ]

        delegation_prompt = (
            f"You are a task delegation manager. Break down the following task "
            f"into {len(self.workers)} or fewer sub-tasks that can be executed in parallel.\n\n"
            f"Main task: {task_description}\n\n"
            f"Available workers: {', '.join(self.workers.keys())}\n\n"
            f"Respond with a JSON array of sub-tasks, each with 'description' and 'assigned_to' fields.\n"
            f"Example: [{{'description': 'Research topic', 'assigned_to': 'researcher'}}]"
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
                # Fallback: 返回为每个 Worker 分配相同任务
                tasks_data = [
                    {"description": task_description, "assigned_to": name}
                    for name in self.workers.keys()
                ]

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

            # 如果没有有效子任务，fallback
            if not sub_tasks:
                sub_tasks = [
                    CrewTask(description=task_description, assigned_to=name)
                    for name in self.workers.keys()
                ]

            return sub_tasks

        except Exception:
            # 任何错误都 fallback
            logger.warning("Task delegation failed, using equal distribution", exc_info=True)
            return [
                CrewTask(description=task_description, assigned_to=name)
                for name in self.workers.keys()
            ]

    # ------------------------------------------------------------------
    # Manager 结果聚合
    # ------------------------------------------------------------------

    async def _aggregate(
        self,
        original_task: str,
        worker_results: list[CrewWorkerResult],
        context: dict[str, Any],
    ) -> CrewWorkerResult:
        """Manager 聚合所有 Worker 结果.

        将多个 Worker 的输出合并为统一的最终答案。
        """
        if not self.manager:
            # 无 Manager 时，简单拼接
            combined = "\n\n".join(
                f"## {r.worker_name}\n{r.output}" for r in worker_results if r.success
            )
            return CrewWorkerResult(
                worker_name="aggregation",
                task=CrewTask(description=original_task),
                output=combined or "No successful worker results",
                success=True,
            )

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
            logger.warning("Manager aggregation failed, using simple concatenation", exc_info=True)
            combined = "\n\n".join(
                f"## {r.worker_name}\n{r.output}" for r in worker_results if r.success
            )
            return CrewWorkerResult(
                worker_name=self.manager.config.name,
                task=CrewTask(description=original_task),
                output=combined or f"Aggregation failed: {e}",
                success=True,
            )

    # ------------------------------------------------------------------
    # 共享上下文管理
    # ------------------------------------------------------------------

    def _trim_shared_context(self) -> None:
        """限制 shared_context 大小，防止无限增长."""
        import json

        try:
            size = len(json.dumps(self.shared_context, ensure_ascii=False).encode("utf-8"))
        except Exception:
            return

        if size > self.config.max_shared_context_size:
            # 截断 worker_outputs 中的长输出
            for name, data in self.shared_context.get("worker_outputs", {}).items():
                if isinstance(data, dict) and "output" in data:
                    output = data["output"]
                    if len(output) > 5000:
                        data["output"] = output[:5000] + "... [truncated]"

    # ------------------------------------------------------------------
    # EventBus 事件发布
    # ------------------------------------------------------------------

    async def _publish_event(
        self,
        step: str,
        data: dict[str, Any],
    ) -> None:
        """通过 EventBus 发布 Crew 执行事件."""
        if not self.event_bus:
            return

        try:
            await self.event_bus.publish({
                "type": "crew_step",
                "crew_id": self.crew_id,
                "step": step,
                "data": data,
            })
        except Exception:
            # 事件发布失败不应阻塞主流程
            logger.warning("EventBus publish failed for crew step '%s'", step, exc_info=True)

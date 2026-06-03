"""Eval 运行器.

Phase 6.5: 批量执行评估，汇总结果。
"""

from __future__ import annotations

from typing import Any

from nexus.agent.base import AgentConfig, BaseAgent, Task
from nexus.eval.evaluators import EvalResult, create_evaluator
from nexus.models.eval import EvalRun


class EvalRunner:
    """评估运行器.

    批量执行评估流程：
    1. 遍历 dataset
    2. 用 Agent 生成输出
    3. 用 Evaluator 打分
    4. 汇总结果
    """

    async def run(
        self,
        eval_run: EvalRun,
        agent_config: AgentConfig | None = None,
    ) -> dict[str, Any]:
        """执行评估运行.

        Args:
            eval_run: 评估运行记录（含 dataset）
            agent_config: 用于生成输出的 Agent 配置

        Returns:
            汇总结果字典
        """
        eval_run.status = "running"

        dataset = eval_run.dataset or []
        if not dataset:
            result = {
                "status": "completed",
                "total": 0,
                "passed": 0,
                "failed": 0,
                "avg_score": 0.0,
                "details": [],
            }
            eval_run.results = result
            eval_run.status = "completed"
            return result

        # 创建 Evaluator
        evaluator = create_evaluator(eval_run.eval_type or "exact_match")

        # 创建 Agent（如果需要生成输出）
        agent = None
        if agent_config:
            agent = BaseAgent(config=agent_config)

        details = []
        passed_count = 0
        total_score = 0.0

        for i, item in enumerate(dataset):
            input_data = item.get("input", {})
            expected = item.get("expected")

            # 生成实际输出（如果有 Agent）
            if agent:
                task = Task(description=str(input_data))
                try:
                    agent_result = await agent.execute(task)
                    actual = agent_result.output
                except Exception as e:
                    actual = f"[ERROR] {str(e)}"
            else:
                actual = item.get("actual", "")

            # 评估
            eval_result = await evaluator.evaluate(input_data, actual, expected)

            if eval_result.passed:
                passed_count += 1
            total_score += eval_result.score

            details.append({
                "index": i,
                "input": input_data,
                "expected": expected,
                "actual": actual,
                "score": eval_result.score,
                "passed": eval_result.passed,
                "reasoning": eval_result.reasoning,
            })

        total = len(dataset)
        result = {
            "status": "completed",
            "total": total,
            "passed": passed_count,
            "failed": total - passed_count,
            "pass_rate": round(passed_count / total, 4) if total > 0 else 0.0,
            "avg_score": round(total_score / total, 4) if total > 0 else 0.0,
            "details": details,
        }

        eval_run.results = result
        eval_run.status = "completed"
        return result

"""Evaluator 接口与实现.

Phase 6.5: LLM-as-Judge, ExactMatch, RegexMatch Evaluators。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class EvalResult:
    """单条评估结果."""

    score: float  # 0-1
    passed: bool
    reasoning: str = ""
    metadata: dict[str, Any] | None = None


class Evaluator(ABC):
    """评估器抽象基类."""

    @abstractmethod
    async def evaluate(
        self,
        input_data: dict[str, Any],
        actual_output: str,
        expected_output: str | None,
    ) -> EvalResult:
        """评估单条输出.

        Args:
            input_data: 原始输入数据
            actual_output: 实际输出
            expected_output: 期望输出（可为 None）

        Returns:
            EvalResult
        """


class LLMJudgeEvaluator(Evaluator):
    """LLM-as-Judge：用另一个 LLM 评估输出质量."""

    def __init__(self, criteria: str = "accuracy", model: str = "gpt-4o-mini"):
        self.criteria = criteria
        self.model = model

    async def evaluate(
        self,
        input_data: dict[str, Any],
        actual_output: str,
        expected_output: str | None,
    ) -> EvalResult:
        """使用 LLM 评估回答质量.

        构建 judge prompt，让 LLM 给出 0-1 分数和理由。
        """
        from nexus.services.llm_service import LLMService

        service = LLMService()

        judge_prompt = self._build_judge_prompt(
            input_data, actual_output, expected_output
        )

        try:
            response = await service.generate(
                system_prompt="You are an expert evaluator. Assess the quality of the response based on the given criteria. Output ONLY a JSON object with keys: score (0-1), passed (boolean), reasoning (string).",
                user_prompt=judge_prompt,
                model=self.model,
                response_format={"type": "json_object"},
            )

            import json

            result = json.loads(response.content)
            score = float(result.get("score", 0))
            passed = bool(result.get("passed", score >= 0.7))
            reasoning = result.get("reasoning", "")

            return EvalResult(
                score=score,
                passed=passed,
                reasoning=reasoning,
            )
        except Exception as e:
            return EvalResult(
                score=0.0,
                passed=False,
                reasoning=f"Eval failed: {str(e)}",
            )

    def _build_judge_prompt(
        self,
        input_data: dict[str, Any],
        actual_output: str,
        expected_output: str | None,
    ) -> str:
        parts = [
            f"Criteria: {self.criteria}",
            f"Input: {input_data.get('input', '')}",
            f"Expected: {expected_output or 'N/A'}",
            f"Actual: {actual_output}",
            "\nPlease evaluate the actual response against the expected output based on the criteria."
            "Score from 0 to 1, where 1 is perfect.",
        ]
        return "\n\n".join(parts)


class ExactMatchEvaluator(Evaluator):
    """精确匹配评估器."""

    async def evaluate(
        self,
        input_data: dict[str, Any],
        actual_output: str,
        expected_output: str | None,
    ) -> EvalResult:
        if expected_output is None:
            return EvalResult(
                score=0.0,
                passed=False,
                reasoning="No expected output provided",
            )

        passed = actual_output.strip() == expected_output.strip()
        return EvalResult(
            score=1.0 if passed else 0.0,
            passed=passed,
            reasoning="Exact match" if passed else "Outputs differ",
        )


class RegexMatchEvaluator(Evaluator):
    """正则匹配评估器."""

    def __init__(self, pattern: str = ".*"):
        import re

        self.pattern = re.compile(pattern)

    async def evaluate(
        self,
        input_data: dict[str, Any],
        actual_output: str,
        expected_output: str | None,
    ) -> EvalResult:
        matched = bool(self.pattern.search(actual_output))
        return EvalResult(
            score=1.0 if matched else 0.0,
            passed=matched,
            reasoning=f"Pattern {'matched' if matched else 'not matched'}",
        )


class ContainsEvaluator(Evaluator):
    """包含子串评估器."""

    def __init__(self, substring: str = ""):
        self.substring = substring

    async def evaluate(
        self,
        input_data: dict[str, Any],
        actual_output: str,
        expected_output: str | None,
    ) -> EvalResult:
        contains = self.substring in actual_output
        return EvalResult(
            score=1.0 if contains else 0.0,
            passed=contains,
            reasoning=f"Substring {'found' if contains else 'not found'}",
        )


def create_evaluator(eval_type: str, **kwargs: Any) -> Evaluator:
    """工厂函数：根据类型创建 Evaluator."""
    evaluators = {
        "llm_judge": LLMJudgeEvaluator,
        "exact_match": ExactMatchEvaluator,
        "regex": RegexMatchEvaluator,
        "contains": ContainsEvaluator,
    }
    cls = evaluators.get(eval_type)
    if not cls:
        raise ValueError(f"Unknown eval type: {eval_type}")
    return cls(**kwargs)

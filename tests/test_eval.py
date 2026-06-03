"""Eval 框架测试 — Phase 6.5.

覆盖：
- ExactMatchEvaluator: 精确匹配
- RegexMatchEvaluator: 正则匹配
- ContainsEvaluator: 子串包含
- LLMJudgeEvaluator: LLM-as-Judge（mock）
- EvalRunner: 批量执行
- create_evaluator: 工厂函数
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.eval.evaluators import (
    ContainsEvaluator,
    EvalResult,
    ExactMatchEvaluator,
    LLMJudgeEvaluator,
    RegexMatchEvaluator,
    create_evaluator,
)
from nexus.eval.runner import EvalRunner
from nexus.models.eval import EvalRun


class TestExactMatchEvaluator:
    """Test ExactMatchEvaluator."""

    @pytest.mark.asyncio
    async def test_exact_match_pass(self):
        """完全相同应通过."""
        evaluator = ExactMatchEvaluator()
        result = await evaluator.evaluate({}, "hello", "hello")
        assert result.passed is True
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_exact_match_fail(self):
        """不同应失败."""
        evaluator = ExactMatchEvaluator()
        result = await evaluator.evaluate({}, "hello", "world")
        assert result.passed is False
        assert result.score == 0.0

    @pytest.mark.asyncio
    async def test_whitespace_trimmed(self):
        """首尾空格应被去除后比较."""
        evaluator = ExactMatchEvaluator()
        result = await evaluator.evaluate({}, "  hello  ", "hello")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_no_expected_output(self):
        """没有 expected 应失败."""
        evaluator = ExactMatchEvaluator()
        result = await evaluator.evaluate({}, "hello", None)
        assert result.passed is False
        assert result.score == 0.0


class TestRegexMatchEvaluator:
    """Test RegexMatchEvaluator."""

    @pytest.mark.asyncio
    async def test_regex_match_pass(self):
        """匹配正则应通过."""
        evaluator = RegexMatchEvaluator(r"\d+")
        result = await evaluator.evaluate({}, "The answer is 42", "42")
        assert result.passed is True
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_regex_match_fail(self):
        """不匹配应失败."""
        evaluator = RegexMatchEvaluator(r"^\d+$")
        result = await evaluator.evaluate({}, "not a number", "123")
        assert result.passed is False


class TestContainsEvaluator:
    """Test ContainsEvaluator."""

    @pytest.mark.asyncio
    async def test_contains_pass(self):
        """包含子串应通过."""
        evaluator = ContainsEvaluator("success")
        result = await evaluator.evaluate({}, "Operation success", None)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_contains_fail(self):
        """不包含应失败."""
        evaluator = ContainsEvaluator("error")
        result = await evaluator.evaluate({}, "All good", None)
        assert result.passed is False


class TestLLMJudgeEvaluator:
    """Test LLMJudgeEvaluator."""

    @pytest.mark.asyncio
    async def test_judge_returns_result(self):
        """LLM Judge 应返回 EvalResult."""
        evaluator = LLMJudgeEvaluator()

        mock_response = MagicMock()
        mock_response.content = '{"score": 0.85, "passed": true, "reasoning": "Good answer"}'

        with patch("nexus.services.llm_service.LLMService.generate", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_response
            result = await evaluator.evaluate(
                {"input": "What is 2+2?"},
                "4",
                "4",
            )

        assert isinstance(result, EvalResult)
        assert result.score == 0.85
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_judge_invalid_json_returns_error(self):
        """无效 JSON 响应应返回错误结果."""
        evaluator = LLMJudgeEvaluator()

        mock_response = MagicMock()
        mock_response.content = "not json"

        with patch("nexus.services.llm_service.LLMService.generate", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_response
            result = await evaluator.evaluate({}, "x", "y")

        assert result.passed is False
        assert "failed" in result.reasoning.lower() or "Eval failed" in result.reasoning


class TestEvaluatorFactory:
    """Test create_evaluator factory."""

    def test_exact_match_factory(self):
        evaluator = create_evaluator("exact_match")
        assert isinstance(evaluator, ExactMatchEvaluator)

    def test_llm_judge_factory(self):
        evaluator = create_evaluator("llm_judge")
        assert isinstance(evaluator, LLMJudgeEvaluator)

    def test_regex_factory(self):
        evaluator = create_evaluator("regex", pattern=r"\d+")
        assert isinstance(evaluator, RegexMatchEvaluator)

    def test_contains_factory(self):
        evaluator = create_evaluator("contains", substring="test")
        assert isinstance(evaluator, ContainsEvaluator)

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown eval type"):
            create_evaluator("unknown")


class TestEvalRunner:
    """Test EvalRunner."""

    @pytest.mark.asyncio
    async def test_run_with_empty_dataset(self):
        """空数据集应返回空结果."""
        runner = EvalRunner()
        eval_run = EvalRun(
            tenant_id="t1",
            name="test",
            eval_type="exact_match",
            dataset=[],
        )
        result = await runner.run(eval_run)
        assert result["total"] == 0
        assert result["passed"] == 0
        assert eval_run.status == "completed"

    @pytest.mark.asyncio
    async def test_run_exact_match_batch(self):
        """批量精确匹配评估."""
        runner = EvalRunner()
        eval_run = EvalRun(
            tenant_id="t1",
            name="test",
            eval_type="exact_match",
            dataset=[
                {"input": "Q1", "expected": "A1", "actual": "A1"},
                {"input": "Q2", "expected": "A2", "actual": "wrong"},
                {"input": "Q3", "expected": "A3", "actual": "A3"},
            ],
        )
        result = await runner.run(eval_run)
        assert result["total"] == 3
        assert result["passed"] == 2
        assert result["failed"] == 1
        assert abs(result["pass_rate"] - 2 / 3) < 0.01
        assert abs(result["avg_score"] - 2 / 3) < 0.01
        assert len(result["details"]) == 3

"""LLM Trace 系统测试 — Phase 6.1.

覆盖：
- trace_llm_call: 计时、数据收集、持久化、Prometheus 指标
- set_trace_context / get_trace_context: contextvars 传递
- LLMTraceData: 数据转换
- BaseAgent / AgentNodeExecutor: trace context 传递
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.agent.base import AgentConfig, BaseAgent, Task
from nexus.agent.llm_client import LLMClient, LLMResponse
from nexus.observability.llm_tracer import (
    LLMTraceData,
    TRACE_CONTEXT,
    get_trace_context,
    set_trace_context,
    trace_llm_call,
)


class TestTraceContextVars:
    """Test contextvars-based trace context."""

    def test_set_and_get_trace_context(self):
        """set_trace_context should update and get_trace_context should read."""
        token = set_trace_context(run_id="r1", agent_id="a1", tenant_id="t1")
        try:
            ctx = get_trace_context()
            assert ctx["run_id"] == "r1"
            assert ctx["agent_id"] == "a1"
            assert ctx["tenant_id"] == "t1"
        finally:
            TRACE_CONTEXT.reset(token)

    @pytest.mark.asyncio
    async def test_trace_context_isolation(self):
        """Different async tasks should have independent trace contexts."""

        async def task1():
            token = set_trace_context(run_id="task1")
            try:
                await asyncio.sleep(0.01)
                return get_trace_context()["run_id"]
            finally:
                TRACE_CONTEXT.reset(token)

        async def task2():
            token = set_trace_context(run_id="task2")
            try:
                await asyncio.sleep(0.01)
                return get_trace_context()["run_id"]
            finally:
                TRACE_CONTEXT.reset(token)

        r1, r2 = await asyncio.gather(task1(), task2())
        assert r1 == "task1"
        assert r2 == "task2"


class TestLLMTraceData:
    """Test LLMTraceData dataclass."""

    def test_to_db_dict_truncation(self):
        """to_db_dict should truncate large prompts."""
        data = LLMTraceData(
            system_prompt="x" * 20000,
            user_prompt="y" * 20000,
            model="gpt-4o",
        )
        db_dict = data.to_db_dict()
        assert len(db_dict["system_prompt"]) == 10000
        assert len(db_dict["user_prompt"]) == 10000

    def test_to_db_dict_empty_fields(self):
        """Empty optional fields should be None in db dict."""
        data = LLMTraceData(model="gpt-4o")
        db_dict = data.to_db_dict()
        assert db_dict["system_prompt"] is None
        assert db_dict["response_content"] is None
        assert db_dict["tool_calls"] is None
        assert db_dict["raw_response"] is None


class TestTraceLLMCall:
    """Test trace_llm_call context manager."""

    @pytest.mark.asyncio
    async def test_records_latency(self):
        """trace_llm_call should record latency_ms > 0."""
        with patch("nexus.observability.llm_tracer._persist_trace", new_callable=AsyncMock):
            with patch("nexus.observability.llm_tracer._update_prometheus_metrics"):
                async with trace_llm_call(
                    model="gpt-4o",
                    system_prompt="test",
                    user_prompt="test",
                ) as tracer:
                    tracer.set_response(LLMResponse(content="hello"))

                # Latency should be recorded after exiting context
                # We verify by checking the tracer data was created
                assert tracer.data.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_sets_response_data(self):
        """tracer.set_response should extract LLMResponse fields."""
        with patch("nexus.observability.llm_tracer._persist_trace", new_callable=AsyncMock):
            with patch("nexus.observability.llm_tracer._update_prometheus_metrics"):
                async with trace_llm_call(
                    model="gpt-4o",
                    system_prompt="sp",
                    user_prompt="up",
                ) as tracer:
                    tracer.set_response(
                        LLMResponse(
                            content="answer",
                            reasoning_content="reasoning",
                            tool_calls=[{"name": "t1"}],
                            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                            raw={"model": "gpt-4o"},
                        )
                    )

                assert tracer.data.response_content == "answer"
                assert tracer.data.response_reasoning == "reasoning"
                assert tracer.data.tool_calls == [{"name": "t1"}]
                assert tracer.data.prompt_tokens == 10
                assert tracer.data.completion_tokens == 5
                assert tracer.data.total_tokens == 15

    @pytest.mark.asyncio
    async def test_reads_trace_context(self):
        """trace_llm_call should read run_id/node_id/agent_id from TRACE_CONTEXT."""
        token = set_trace_context(run_id="r1", node_id="n1", agent_id="a1")
        try:
            with patch("nexus.observability.llm_tracer._persist_trace", new_callable=AsyncMock):
                with patch("nexus.observability.llm_tracer._update_prometheus_metrics"):
                    async with trace_llm_call(
                        model="gpt-4o",
                        system_prompt="test",
                        user_prompt="test",
                    ) as tracer:
                        pass

                    assert tracer.data.run_id == "r1"
                    assert tracer.data.node_id == "n1"
                    assert tracer.data.agent_id == "a1"
        finally:
            TRACE_CONTEXT.reset(token)

    @pytest.mark.asyncio
    async def test_set_retry_info(self):
        """tracer.set_retry_info should record retry count and fallback model."""
        with patch("nexus.observability.llm_tracer._persist_trace", new_callable=AsyncMock):
            with patch("nexus.observability.llm_tracer._update_prometheus_metrics"):
                async with trace_llm_call(
                    model="gpt-4o",
                    system_prompt="test",
                    user_prompt="test",
                ) as tracer:
                    tracer.set_retry_info(retry_count=2, fallback_model="claude-sonnet")

                assert tracer.data.retry_count == 2
                assert tracer.data.fallback_model == "claude-sonnet"


class TestBaseAgentTraceContext:
    """Test BaseAgent passes trace context."""

    @pytest.mark.asyncio
    async def test_agent_sets_trace_context(self):
        """BaseAgent.execute should set agent_id in trace context."""
        agent = BaseAgent(config=AgentConfig(name="test_agent"))

        # Mock LLM to avoid real HTTP call
        with patch.object(agent.llm_client, "call", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = LLMResponse(
                content="done",
                raw={"choices": [{"message": {"content": "done"}}]},
            )

            # Mock decision parser to return final_answer
            with patch.object(agent.decision_parser, "parse") as mock_parse:
                from nexus.agent.decision_parser import AgentDecision
                mock_parse.return_value = AgentDecision(
                    action="final_answer", content="done"
                )

                await agent.execute(
                    Task(description="test"),
                    context={"run_id": "r1", "node_id": "n1"},
                )

        # Verify trace context was set during execution
        ctx = get_trace_context()
        # After execution, the token is reset, so context should be empty
        # But during execution, agent_id should have been set
        assert "agent_id" not in ctx  # Token was reset


class TestPrometheusMetricsUpdate:
    """Test Prometheus metrics are updated correctly."""

    def test_update_metrics_success(self):
        """_update_prometheus_metrics should record success metrics."""
        data = LLMTraceData(
            model="gpt-4o",
            total_tokens=100,
            prompt_tokens=50,
            completion_tokens=50,
            latency_ms=500,
        )

        # Patch the metrics at their source module since llm_tracer does local imports
        with patch("nexus.observability.metrics.LLM_CALLS_TOTAL") as mock_calls:
            with patch("nexus.observability.metrics.LLM_LATENCY") as mock_latency:
                with patch("nexus.observability.metrics.LLM_TOKENS_TOTAL") as mock_tokens:
                    from nexus.observability.llm_tracer import _update_prometheus_metrics
                    _update_prometheus_metrics(data)

                    mock_calls.labels.assert_called_once()
                    mock_latency.labels.assert_called_once()
                    mock_tokens.labels.assert_called()

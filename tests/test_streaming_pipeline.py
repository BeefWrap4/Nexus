"""S5-2: LLM → EventBus 流式通路测试.

验证 BaseAgent 启用 streaming=True 时：
1. 走 LLMService.stream_generate 路径
2. 每个 LLMStreamChunk 立即被 publish 到 EventBus（type=llm_stream_chunk）
3. 最终 stream_end 事件发出（type=llm_stream_end）
4. 累积的 content 被组装成完整 LLMResponse 供 decision_parser 用
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.agent.base import AgentConfig, BaseAgent, Task
from nexus.agent.llm_client import LLMResponse, LLMStreamChunk
from nexus.agent.decision_parser import AgentDecision


def _chunk(content: str = "", reasoning: str = "", finish: str | None = None) -> LLMStreamChunk:
    return LLMStreamChunk(
        content=content, reasoning_content=reasoning, finish_reason=finish,
    )


class _StubRegistry:
    def __init__(self):
        self._tool = MagicMock(
            name="noop", description="stub",
            schema={"type": "function", "function": {"name": "noop",
                "description": "stub", "parameters": {"type": "object"}}},
        )

    async def execute(self, tool_name, params, context=None):
        from nexus.tools.registry import ToolResult
        return ToolResult(success=True, data={})

    def list_tools(self, context=None):
        return [MagicMock(name="noop", description="stub", schema=self._tool.schema)]

    def get_tool(self, name):
        return self._tool


class TestLLMStreamingPipeline:
    """S5-2 验证 LLM 流式 chunk 真的被推到 EventBus."""

    @pytest.mark.asyncio
    async def test_streaming_chunks_published_to_eventbus(self):
        """启用 streaming 时，每个 chunk 立即 publish llm_stream_chunk."""
        chunks_published: list[dict] = []
        # 模拟 EventBus — 只记录 publish 调用
        mock_event_bus = MagicMock()
        mock_event_bus.publish = AsyncMock(side_effect=lambda ev: chunks_published.append(ev) or None)

        # 模拟 LLMService.stream_generate — yield 3 个 chunk
        async def mock_stream(*args, **kwargs):
            yield _chunk("Hello")
            yield _chunk(" world", finish="stop")
        llm_service = MagicMock()
        llm_service.stream_generate = mock_stream

        # 决策 parser：final_answer 看到 "Hello world" 后返回
        from nexus.agent import base as base_mod
        class StubParser:
            def parse(self, raw):
                # 检查累积 content 是不是 "Hello world"
                content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
                if "Hello world" in content:
                    return AgentDecision(action="final_answer", content=content)
                return AgentDecision(action="think", content="wait")

        cfg = AgentConfig(name="stream-test", streaming=True, max_iterations=3)
        agent = BaseAgent(
            config=cfg,
            llm_client=MagicMock(),
            llm_service=llm_service,
            tool_registry=_StubRegistry(),
            memory=None,
            event_bus=mock_event_bus,
        )
        agent.decision_parser = StubParser()

        result = await agent.execute(Task(description="go"))

        # 验证 1: 至少 2 个 llm_stream_chunk + 1 个 llm_stream_end
        chunk_events = [e for e in chunks_published if e.get("type") == "llm_stream_chunk"]
        end_events = [e for e in chunks_published if e.get("type") == "llm_stream_end"]

        assert len(chunk_events) >= 2, (
            f"应至少 2 个 chunk，实际 {len(chunk_events)}"
        )
        assert len(end_events) == 1, (
            f"应正好 1 个 stream_end，实际 {len(end_events)}"
        )

        # 验证 2: 第一个 chunk 的 content 是 "Hello"
        assert chunk_events[0].get("content") == "Hello", (
            f"第一个 chunk content 错: {chunk_events[0]}"
        )
        # 验证 3: 第二个 chunk 的 content 是 " world"
        assert chunk_events[1].get("content") == " world", (
            f"第二个 chunk content 错: {chunk_events[1]}"
        )

        # 验证 4: stream_end 包含 total_chars
        assert end_events[0].get("total_chars") == len("Hello world") == 11

    @pytest.mark.asyncio
    async def test_non_streaming_does_not_publish_stream_chunks(self):
        """streaming=False 时，EventBus 应不被 publish stream_* 事件。"""
        chunks_published: list[dict] = []
        mock_event_bus = MagicMock()
        mock_event_bus.publish = AsyncMock(side_effect=lambda ev: chunks_published.append(ev) or None)

        async def mock_generate(*args, **kwargs):
            return LLMResponse(
                content="all done",
                raw={"choices": [{"message": {"content": "all done"}, "finish_reason": "stop"}]},
            )
        llm_service = MagicMock()
        llm_service.generate = AsyncMock(side_effect=mock_generate)

        from nexus.agent import base as base_mod
        class StubParser:
            def parse(self, raw):
                return AgentDecision(action="final_answer", content="all done")

        cfg = AgentConfig(name="non-stream-test", streaming=False, max_iterations=2)
        agent = BaseAgent(
            config=cfg,
            llm_client=MagicMock(),
            llm_service=llm_service,
            tool_registry=_StubRegistry(),
            memory=None,
            event_bus=mock_event_bus,
        )
        agent.decision_parser = StubParser()

        await agent.execute(Task(description="go"))

        # 没有 stream_* 事件
        stream_events = [e for e in chunks_published if "stream" in e.get("type", "")]
        assert len(stream_events) == 0, (
            f"streaming=False 时不应有 stream 事件，实际: {stream_events}"
        )

    @pytest.mark.asyncio
    async def test_streaming_without_eventbus_falls_back_to_non_streaming(self):
        """streaming=True 但 event_bus=None 时，应回退到非流式路径（generate）."""
        # 当条件 self.config.streaming AND self.event_bus 中 event_bus 为 None，
        # 走 generate() 路径（兼容旧调用）。
        async def mock_generate(*args, **kwargs):
            return LLMResponse(
                content="fallback done",
                raw={"choices": [{"message": {"content": "fallback done"}, "finish_reason": "stop"}]},
            )
        llm_service = MagicMock()
        llm_service.generate = AsyncMock(side_effect=mock_generate)

        from nexus.agent import base as base_mod
        class StubParser:
            def parse(self, raw):
                return AgentDecision(action="final_answer", content="fallback done")

        cfg = AgentConfig(name="no-bus", streaming=True, max_iterations=2)
        agent = BaseAgent(
            config=cfg,
            llm_client=MagicMock(),
            llm_service=llm_service,
            tool_registry=_StubRegistry(),
            memory=None,
            event_bus=None,  # 关键：触发回退到非流式
        )
        agent.decision_parser = StubParser()

        result = await agent.execute(Task(description="go"))
        assert result.output == "fallback done"
        # 验证：走的 generate 而不是 stream_generate
        llm_service.generate.assert_awaited()
        llm_service.stream_generate.assert_not_called()

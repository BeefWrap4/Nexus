"""S5-1: BaseAgent 真 ReAct messages 列表 + role:tool 测试."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.agent.base import AgentConfig, BaseAgent
from nexus.agent.llm_client import LLMResponse
from nexus.agent.decision_parser import AgentDecision


def _make_response(content: str, tool_calls: list | None = None) -> LLMResponse:
    """构造 LLMResponse 对象，模拟 OpenAI chat completion 格式."""
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
        msg["content"] = None
    raw = {"choices": [{"message": msg, "finish_reason": "stop"}]}
    return LLMResponse(content=content, raw=raw, tool_calls=tool_calls or [])


def _make_tool_call(call_id: str, name: str, args: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(args),
        },
    }


class _StubRegistry:
    """最小可用 ToolRegistry：execute 返回带 data 的 ToolResult."""

    def __init__(self, data=None, fail: bool = False):
        self._data = data or {"echo": True}
        self._fail = fail
        self._tool = MagicMock(
            name="fetch",
            description="stub tool",
            schema={
                "type": "function",
                "function": {
                    "name": "fetch",
                    "description": "stub tool",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        )

    async def execute(self, tool_name, params, context=None):
        from nexus.tools.registry import ToolResult
        if self._fail:
            return ToolResult(success=False, error="intentional")
        return ToolResult(success=True, data={**self._data, "tool": tool_name})

    def list_tools(self, context=None):
        return [MagicMock(name="fetch", description="stub", schema=self._tool.schema)]

    def get_tool(self, name):
        return self._tool


class TestReActMessagesFlow:
    """验证 BaseAgent._execute_loop 用真 messages list 而不是字符串拼接."""

    def _build_agent(self, llm_service, tool_registry) -> BaseAgent:
        cfg = AgentConfig(name="react-msg-test", max_iterations=3)
        agent = BaseAgent(
            config=cfg,
            llm_client=MagicMock(),
            llm_service=llm_service,
            tool_registry=tool_registry,
            memory=None,
        )
        return agent

    @pytest.mark.asyncio
    async def test_tool_call_uses_role_tool_messages(self):
        """修复 (S5-1): tool 结果应作为 role:tool 消息传给下一轮 LLM。"""
        # 跟踪 LLMService.generate 收到的 messages 参数
        captured: list[list[dict]] = []

        async def mock_generate(*args, **kwargs):
            captured.append(kwargs.get("messages") or [])
            # 第一次：返回 tool_call（"fetch_data"）
            # 第二次：返回 final_answer
            if len(captured) == 1:
                return _make_response("", tool_calls=[
                    _make_tool_call("call_1", "fetch_data", {"q": "x"}),
                ])
            return _make_response("done")

        llm_service = MagicMock()
        llm_service.generate = AsyncMock(side_effect=mock_generate)

        from nexus.agent.decision_parser import AgentDecision
        from nexus.agent.llm_client import LLMResponse

        # 第一次调用返回 tool_call 时 parser 需给 action="tool_call"
        from nexus.agent import base as base_mod
        original_parser = base_mod.DecisionParser

        class StubParser:
            def __init__(self, *a, **k): pass

            def parse(self, raw):
                # 第一次：tool_call；第二次：final_answer
                if not captured or len(captured) == 1:
                    return AgentDecision(
                        action="tool_call",
                        tool_name="fetch_data",
                        tool_params={"q": "x"},
                        reasoning="need data",
                    )
                return AgentDecision(action="final_answer", content="all done")

        base_mod.DecisionParser = StubParser

        try:
            from nexus.agent.base import Task
            agent = self._build_agent(llm_service, _StubRegistry(data={"v": 42}))
            agent.decision_parser = StubParser()  # 显式覆盖
            result = await agent.execute(Task(description="go"))
        finally:
            base_mod.DecisionParser = original_parser

        # 验证 1：LLM 至少被调了 2 次（第一轮 tool_call，第二轮 final）
        assert len(captured) >= 2, f"expected 2+ LLM calls, got {len(captured)}"

        # 验证 2：第二轮的 messages 必须包含 role:tool 消息（S5-1 修复点）
        second_call_messages = captured[-1]
        tool_messages = [m for m in second_call_messages if m.get("role") == "tool"]
        assert len(tool_messages) >= 1, (
            "S5-1: 第二轮 messages 必须包含 role:tool 消息，"
            f"实际 messages: {second_call_messages}"
        )
        # tool 消息必须有 tool_call_id 关联到上一条 assistant 消息的 tool_calls[0].id
        assert tool_messages[0].get("tool_call_id"), (
            f"role:tool 消息必须带 tool_call_id，实际: {tool_messages[0]}"
        )
        # tool 消息的 content 包含 tool 返回数据
        assert "fetch_data" in tool_messages[0]["content"] or '"v": 42' in tool_messages[0]["content"] or "v" in tool_messages[0]["content"], (
            f"role:tool 消息内容应包含 tool 返回数据，实际: {tool_messages[0]['content']}"
        )

    @pytest.mark.asyncio
    async def test_assistant_message_carries_tool_call_id(self):
        """第一轮 messages 应包含 role:assistant + tool_calls（含 id）."""
        captured: list[list[dict]] = []

        async def mock_generate(*args, **kwargs):
            captured.append(kwargs.get("messages") or [])
            if len(captured) == 1:
                return _make_response("", tool_calls=[
                    _make_tool_call("call_abc", "fetch", {}),
                ])
            return _make_response("ok")

        llm_service = MagicMock()
        llm_service.generate = AsyncMock(side_effect=mock_generate)

        from nexus.agent import base as base_mod

        class StubParser:
            def parse(self, raw):
                if not captured or len(captured) == 1:
                    return AgentDecision(
                        action="tool_call", tool_name="fetch", tool_params={},
                    )
                return AgentDecision(action="final_answer", content="ok")

        from nexus.agent.base import Task
        cfg = AgentConfig(name="t", max_iterations=3)
        agent = BaseAgent(config=cfg, llm_client=MagicMock(),
                          llm_service=llm_service, tool_registry=_StubRegistry(),
                          memory=None)
        agent.decision_parser = StubParser()

        await agent.execute(Task(description="x"))

        # 第二轮 messages 应该看到 assistant 消息 + tool 消息
        second = captured[-1]
        assistant_msgs = [m for m in second if m.get("role") == "assistant"]
        assert len(assistant_msgs) >= 1
        assert assistant_msgs[0].get("tool_calls"), "assistant 消息必须带 tool_calls"
        assert assistant_msgs[0]["tool_calls"][0]["id"] == "call_abc", (
            f"tool_call id 应从原始响应里保留，实际: {assistant_msgs[0]['tool_calls'][0]}"
        )

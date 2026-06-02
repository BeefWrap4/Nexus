"""RAG Tools 集成测试.

测试 Smart Cache 作为 NEXUS HTTP Tool Provider 的集成，包括:
- RAG Tool 注册和列表
- HTTP 执行器增强（auth_config, URL 模板替换, Schema 参数过滤）
- Agent tool_call 集成
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
from httpx import Response

from nexus.config import settings
from nexus.tools.rag import build_rag_tools, register_rag_tools
from nexus.tools.registry import Tool, ToolRegistry, ToolResult, ToolType


# -----------------------------------------------------------------------------
# Phase 3.1: 配置层测试
# -----------------------------------------------------------------------------

class TestSmartCacheConfig:
    """测试 Smart Cache 配置是否正确加载."""

    def test_smart_cache_url_default(self):
        """默认 URL 应为 localhost:8777."""
        assert settings.SMART_CACHE_URL == "http://localhost:8777"

    def test_smart_cache_timeout_default(self):
        """默认超时 30 秒."""
        assert settings.SMART_CACHE_TIMEOUT == 30.0

    def test_smart_cache_project_id_default(self):
        """默认项目 ID."""
        assert settings.SMART_CACHE_PROJECT_ID == "nexus-default"


# -----------------------------------------------------------------------------
# Phase 3.2: RAG Tools 定义测试
# -----------------------------------------------------------------------------

class TestRAGToolDefinitions:
    """测试 RAG Tool 定义是否正确构建."""

    def test_build_rag_tools_count(self):
        """应生成 5 个 RAG Tools（含流式）."""
        tools = build_rag_tools()
        assert len(tools) == 5
        names = {t.name for t in tools}
        assert names == {"rag_ask", "rag_ask_stream", "rag_embeddings", "rag_intent_match", "rag_history_recall"}

    def test_rag_ask_tool_structure(self):
        """rag_ask Tool 结构正确."""
        tools = {t.name: t for t in build_rag_tools()}
        ask = tools["rag_ask"]

        assert ask.type == ToolType.HTTP
        assert settings.SMART_CACHE_URL.rstrip("/") in ask.config["url"]
        assert ask.config["method"] == "POST"
        assert "prompt" in ask.schema["properties"]
        assert "session_id" in ask.schema["properties"]
        assert ask.schema["required"] == ["prompt", "session_id"]

    def test_rag_history_recall_url_template(self):
        """rag_history_recall 的 URL 应包含模板变量."""
        tools = {t.name: t for t in build_rag_tools()}
        recall = tools["rag_history_recall"]
        assert "{session_id}" in recall.config["url"]

    def test_auth_config_injected_when_api_key_set(self, monkeypatch):
        """当 SMART_CACHE_API_KEY 设置时，auth_config 应包含 header."""
        monkeypatch.setattr(settings, "SMART_CACHE_API_KEY", "sk-test-key")
        tools = {t.name: t for t in build_rag_tools()}
        ask = tools["rag_ask"]
        assert ask.auth_config["type"] == "header"
        assert ask.auth_config["value"] == "sk-test-key"

    def test_auth_config_empty_when_no_api_key(self, monkeypatch):
        """当 SMART_CACHE_API_KEY 为空时，auth_config 为空."""
        monkeypatch.setattr(settings, "SMART_CACHE_API_KEY", None)
        tools = {t.name: t for t in build_rag_tools()}
        ask = tools["rag_ask"]
        assert ask.auth_config == {}


class TestRAGToolRegistration:
    """测试 RAG Tool 注册到 ToolRegistry."""

    def test_register_rag_tools(self):
        """注册后 registry 应包含 4 个 RAG Tools."""
        registry = ToolRegistry()
        register_rag_tools(registry)

        tools = registry.list_tools()
        names = {t.name for t in tools}
        assert "rag_ask" in names
        assert "rag_embeddings" in names
        assert "rag_intent_match" in names
        assert "rag_history_recall" in names

    def test_register_rag_tools_skipped_when_no_url(self, monkeypatch):
        """SMART_CACHE_URL 为空时跳过注册."""
        monkeypatch.setattr(settings, "SMART_CACHE_URL", "")
        registry = ToolRegistry()
        register_rag_tools(registry)

        tools = registry.list_tools()
        names = {t.name for t in tools}
        assert "rag_ask" not in names


# -----------------------------------------------------------------------------
# Phase 3.3: ToolRegistry HTTP 执行器增强测试
# -----------------------------------------------------------------------------

class TestHTTPExecutorEnhancements:
    """测试 HTTP 执行器的增强功能."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_auth_config_header_injection(self):
        """auth_config header 类型应正确注入请求头."""
        route = respx.post("http://test.local/api").mock(return_value=Response(200, json={"ok": True}))

        registry = ToolRegistry()
        tool = Tool(
            name="test_auth",
            description="",
            type=ToolType.HTTP,
            config={"url": "http://test.local/api", "method": "POST"},
            auth_config={"type": "header", "key": "X-API-Key", "value": "secret123"},
        )
        registry.register(tool)

        result = await registry.execute("test_auth", params={"foo": "bar"})

        assert result.success
        assert route.called
        request = route.calls.last.request
        assert request.headers["X-API-Key"] == "secret123"

    @respx.mock
    @pytest.mark.asyncio
    async def test_auth_config_bearer_injection(self):
        """auth_config bearer 类型应正确注入 Authorization 头."""
        route = respx.post("http://test.local/api").mock(return_value=Response(200, json={"ok": True}))

        registry = ToolRegistry()
        tool = Tool(
            name="test_bearer",
            description="",
            type=ToolType.HTTP,
            config={"url": "http://test.local/api", "method": "POST"},
            auth_config={"type": "bearer", "token": "jwt-token-xyz"},
        )
        registry.register(tool)

        result = await registry.execute("test_bearer", params={})

        assert result.success
        request = route.calls.last.request
        assert request.headers["Authorization"] == "Bearer jwt-token-xyz"

    @respx.mock
    @pytest.mark.asyncio
    async def test_url_template_replacement(self):
        """URL 模板变量应从 params 中替换."""
        route = respx.post("http://test.local/sessions/s-123/history/relevant").mock(
            return_value=Response(200, json={"results": []})
        )

        registry = ToolRegistry()
        tool = Tool(
            name="test_url_template",
            description="",
            type=ToolType.HTTP,
            config={"url": "http://test.local/sessions/{session_id}/history/relevant", "method": "POST"},
            schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "query": {"type": "string"},
                },
            },
        )
        registry.register(tool)

        result = await registry.execute(
            "test_url_template",
            params={"session_id": "s-123", "query": "hello"},
        )

        assert result.success
        assert route.called
        request = route.calls.last.request
        # session_id 应从 body 中移除（已用于 URL 替换）
        body = json.loads(request.content)
        assert "session_id" not in body
        assert body["query"] == "hello"

    @respx.mock
    @pytest.mark.asyncio
    async def test_schema_parameter_filtering(self):
        """只应发送 schema 中定义的参数到 HTTP body."""
        route = respx.post("http://test.local/api").mock(return_value=Response(200, json={"ok": True}))

        registry = ToolRegistry()
        tool = Tool(
            name="test_filter",
            description="",
            type=ToolType.HTTP,
            config={"url": "http://test.local/api", "method": "POST"},
            schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                },
            },
        )
        registry.register(tool)

        result = await registry.execute(
            "test_filter",
            params={"prompt": "hi", "extra_field": "should_be_filtered", "another": 123},
        )

        assert result.success
        request = route.calls.last.request
        body = json.loads(request.content)
        assert body == {"prompt": "hi"}
        assert "extra_field" not in body
        assert "another" not in body

    @respx.mock
    @pytest.mark.asyncio
    async def test_no_schema_allows_all_params(self):
        """没有 schema properties 时允许所有参数."""
        route = respx.post("http://test.local/api").mock(return_value=Response(200, json={"ok": True}))

        registry = ToolRegistry()
        tool = Tool(
            name="test_no_schema",
            description="",
            type=ToolType.HTTP,
            config={"url": "http://test.local/api", "method": "POST"},
            schema={},
        )
        registry.register(tool)

        result = await registry.execute(
            "test_no_schema",
            params={"anything": "goes", "number": 42},
        )

        assert result.success
        request = route.calls.last.request
        body = json.loads(request.content)
        assert body["anything"] == "goes"
        assert body["number"] == 42


# -----------------------------------------------------------------------------
# Phase 3.4: Agent 层工具调用集成测试
# -----------------------------------------------------------------------------

class TestAgentToolCallIntegration:
    """测试 Agent tool_call 集成 ToolRegistry."""

    @pytest.mark.asyncio
    async def test_tool_call_with_registry(self):
        """Agent tool_call 应实际调用 ToolRegistry.execute."""
        from nexus.agent.base import AgentConfig, BaseAgent, Task

        # Mock ToolRegistry
        mock_registry = MagicMock()
        mock_registry.execute = AsyncMock(
            return_value=ToolResult(success=True, data={"answer": "42"})
        )

        config = AgentConfig(
            name="test_agent",
            tools=["rag_ask"],
        )
        agent = BaseAgent(config, tool_registry=mock_registry)

        # Mock LLM 返回 tool_call 决策
        with patch.object(agent.llm_client, "call", new_callable=AsyncMock) as mock_llm:
            from nexus.agent.decision_parser import AgentDecision

            # 第一轮: tool_call, 第二轮: final_answer
            mock_llm.side_effect = [
                json.dumps({
                    "action": "tool_call",
                    "tool_name": "rag_ask",
                    "tool_params": {"prompt": "test", "session_id": "s1"},
                    "reasoning": "Need to search",
                }),
                json.dumps({
                    "action": "final_answer",
                    "content": "The answer is 42",
                    "reasoning": "Got it from tool",
                }),
            ]

            # Mock decision parser
            with patch.object(agent.decision_parser, "parse") as mock_parse:
                mock_parse.side_effect = [
                    AgentDecision(
                        action="tool_call",
                        tool_name="rag_ask",
                        tool_params={"prompt": "test", "session_id": "s1"},
                        reasoning="Need to search",
                    ),
                    AgentDecision(
                        action="final_answer",
                        content="The answer is 42",
                        reasoning="Got it from tool",
                    ),
                ]

                result = await agent.execute(
                    Task(description="What is the answer?"),
                    context={"run_id": "r1", "tenant_id": "t1"},
                )

        assert result.output == "The answer is 42"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["tool"] == "rag_ask"

        # 验证 ToolRegistry 被正确调用
        mock_registry.execute.assert_called_once()
        call_args = mock_registry.execute.call_args
        assert call_args.kwargs["tool_name"] == "rag_ask"
        assert call_args.kwargs["params"]["prompt"] == "test"
        assert call_args.kwargs["context"]["run_id"] == "r1"

    @pytest.mark.asyncio
    async def test_tool_call_without_registry(self):
        """没有 ToolRegistry 时应返回友好提示."""
        from nexus.agent.base import AgentConfig, BaseAgent, Task

        config = AgentConfig(name="test_agent", tools=["rag_ask"])
        agent = BaseAgent(config, tool_registry=None)

        with patch.object(agent.llm_client, "call", new_callable=AsyncMock) as mock_llm:
            from nexus.agent.decision_parser import AgentDecision

            mock_llm.side_effect = [
                json.dumps({
                    "action": "tool_call",
                    "tool_name": "rag_ask",
                    "tool_params": {"prompt": "test"},
                }),
                json.dumps({
                    "action": "final_answer",
                    "content": "Done",
                }),
            ]

            with patch.object(agent.decision_parser, "parse") as mock_parse:
                mock_parse.side_effect = [
                    AgentDecision(
                        action="tool_call",
                        tool_name="rag_ask",
                        tool_params={"prompt": "test"},
                    ),
                    AgentDecision(action="final_answer", content="Done"),
                ]

                result = await agent.execute(Task(description="Test"))

        assert result.output == "Done"
        # 没有 ToolRegistry 时 observation 应包含提示信息
        assert len(result.tool_calls) == 1

    @pytest.mark.asyncio
    async def test_tool_call_error_handling(self):
        """Tool 执行失败时应记录错误而不中断 Agent 循环."""
        from nexus.agent.base import AgentConfig, BaseAgent, Task

        mock_registry = MagicMock()
        mock_registry.execute = AsyncMock(
            side_effect=Exception("Smart Cache connection failed")
        )

        config = AgentConfig(name="test_agent", tools=["rag_ask"])
        agent = BaseAgent(config, tool_registry=mock_registry)

        with patch.object(agent.llm_client, "call", new_callable=AsyncMock) as mock_llm:
            from nexus.agent.decision_parser import AgentDecision

            mock_llm.side_effect = [
                json.dumps({
                    "action": "tool_call",
                    "tool_name": "rag_ask",
                    "tool_params": {"prompt": "test"},
                }),
                json.dumps({
                    "action": "final_answer",
                    "content": "Fallback answer",
                }),
            ]

            with patch.object(agent.decision_parser, "parse") as mock_parse:
                mock_parse.side_effect = [
                    AgentDecision(
                        action="tool_call",
                        tool_name="rag_ask",
                        tool_params={"prompt": "test"},
                    ),
                    AgentDecision(action="final_answer", content="Fallback answer"),
                ]

                result = await agent.execute(Task(description="Test"))

        assert result.output == "Fallback answer"
        assert result.status == "success"


# -----------------------------------------------------------------------------
# Phase 3.5: RAG Tool 端到端 Mock 测试
# -----------------------------------------------------------------------------

class TestRAGToolEndToEnd:
    """RAG Tool 端到端 Mock 测试（模拟 Smart Cache 响应）."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_rag_ask_tool_execution(self, monkeypatch):
        """rag_ask Tool 应正确调用 Smart Cache /v1/llm/ask."""
        monkeypatch.setattr(settings, "SMART_CACHE_API_KEY", "sk-test")

        route = respx.post("http://localhost:8777/v1/llm/ask").mock(
            return_value=Response(
                200,
                json={
                    "response": "语义缓存是一种基于向量相似度的缓存机制",
                    "cached": False,
                    "latency_ms": 1200,
                },
            )
        )

        registry = ToolRegistry()
        register_rag_tools(registry)

        result = await registry.execute(
            "rag_ask",
            params={
                "prompt": "什么是语义缓存？",
                "session_id": "test-001",
                "temperature": 0.2,
            },
        )

        assert result.success
        assert result.data["response"] == "语义缓存是一种基于向量相似度的缓存机制"
        assert route.called
        request = route.calls.last.request
        assert request.headers["X-API-Key"] == "sk-test"
        body = json.loads(request.content)
        assert body["prompt"] == "什么是语义缓存？"
        assert body["temperature"] == 0.2
        # session_id 在 URL 中没有模板变量，因此保留在 body 中
        assert body["session_id"] == "test-001"

    @respx.mock
    @pytest.mark.asyncio
    async def test_rag_history_recall_url_template(self, monkeypatch):
        """rag_history_recall 应正确替换 URL 中的 session_id."""
        route = respx.post("http://localhost:8777/v1/sessions/sess-abc/history/relevant").mock(
            return_value=Response(
                200,
                json={
                    "results": [
                        {"role": "user", "content": "之前的提问"},
                        {"role": "assistant", "content": "之前的回答"},
                    ]
                },
            )
        )

        registry = ToolRegistry()
        register_rag_tools(registry)

        result = await registry.execute(
            "rag_history_recall",
            params={"session_id": "sess-abc", "query": "之前的", "top_k": 3},
        )

        assert result.success
        assert len(result.data["results"]) == 2
        assert route.called
        request = route.calls.last.request
        body = json.loads(request.content)
        # session_id 已用于 URL 替换，不应在 body 中
        assert "session_id" not in body
        assert body["query"] == "之前的"
        assert body["top_k"] == 3

    @respx.mock
    @pytest.mark.asyncio
    async def test_rag_embeddings_tool(self):
        """rag_embeddings Tool 应正确调用 Smart Cache /v1/embeddings."""
        route = respx.post("http://localhost:8777/v1/embeddings").mock(
            return_value=Response(
                200,
                json={
                    "cached": True,
                    "embedding": [0.1, 0.2, 0.3],
                    "dim": 3,
                },
            )
        )

        registry = ToolRegistry()
        register_rag_tools(registry)

        result = await registry.execute(
            "rag_embeddings",
            params={"text": "Hello world"},
        )

        assert result.success
        assert result.data["cached"] is True
        assert result.data["dim"] == 3

    @respx.mock
    @pytest.mark.asyncio
    async def test_rag_intent_match_tool(self):
        """rag_intent_match Tool 应正确调用 Smart Cache /v1/intents/match."""
        route = respx.post("http://localhost:8777/v1/intents/match").mock(
            return_value=Response(
                200,
                json={
                    "intent": "knowledge",
                    "confidence": 0.95,
                    "matched_example": "什么是语义缓存？",
                },
            )
        )

        registry = ToolRegistry()
        register_rag_tools(registry)

        result = await registry.execute(
            "rag_intent_match",
            params={"query": "你们支持哪些模型？"},
        )

        assert result.success
        assert result.data["intent"] == "knowledge"
        assert result.data["confidence"] == 0.95

    @respx.mock
    @pytest.mark.asyncio
    async def test_rag_tool_smart_cache_error(self):
        """Smart Cache 返回 500 时应返回失败结果."""
        respx.post("http://localhost:8777/v1/llm/ask").mock(
            return_value=Response(500, text="Internal Server Error")
        )

        registry = ToolRegistry()
        register_rag_tools(registry)

        with pytest.raises(Exception):
            await registry.execute(
                "rag_ask",
                params={"prompt": "test", "session_id": "s1"},
            )

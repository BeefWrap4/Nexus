"""LLM客户端测试.

测试LLMClient的响应解析、调用和流式输出功能。
覆盖率目标: 25% → 60%+
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json
from nexus.agent.llm_client import LLMClient, LLMResponse, LLMStreamChunk
from nexus.exceptions import LLMCallException


@pytest.fixture
def llm_client():
    """创建LLM客户端实例."""
    return LLMClient(
        proxy_url="http://test-proxy:4000",
        api_key="test-api-key",
    )


@pytest.fixture
def sample_openai_response():
    """创建示例OpenAI格式响应."""
    return {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello, world!",
                    "reasoning_content": "Let me think about this...",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        },
    }


@pytest.fixture
def sample_tool_call_response():
    """创建示例工具调用响应."""
    return {
        "id": "chatcmpl-456",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"location": "Beijing"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {
            "prompt_tokens": 15,
            "completion_tokens": 25,
            "total_tokens": 40,
        },
    }


class TestExtractContent:
    """测试内容提取功能."""

    def test_extract_content_from_message(self, llm_client):
        """测试从message提取内容."""
        choice = {
            "message": {
                "content": "Test content",
            }
        }
        content = llm_client._extract_content(choice)
        assert content == "Test content"

    def test_extract_content_from_delta(self, llm_client):
        """测试从delta提取内容（流式）."""
        choice = {
            "delta": {
                "content": "Streaming content",
            }
        }
        content = llm_client._extract_content(choice)
        assert content == "Streaming content"

    def test_extract_content_none(self, llm_client):
        """测试内容为None的情况."""
        choice = {
            "message": {
                "content": None,
            }
        }
        content = llm_client._extract_content(choice)
        assert content == ""

    def test_extract_content_missing(self, llm_client):
        """测试缺少content字段的情况."""
        choice = {
            "message": {},
        }
        content = llm_client._extract_content(choice)
        assert content == ""


class TestExtractReasoning:
    """测试推理内容提取功能."""

    def test_extract_reasoning_content(self, llm_client):
        """测试提取reasoning_content."""
        choice = {
            "message": {
                "reasoning_content": "Deep thinking process...",
            }
        }
        reasoning = llm_client._extract_reasoning(choice)
        assert reasoning == "Deep thinking process..."

    def test_extract_reasoning_field(self, llm_client):
        """测试提取reasoning字段（Anthropic格式）."""
        choice = {
            "delta": {
                "reasoning": "Alternative reasoning format...",
            }
        }
        reasoning = llm_client._extract_reasoning(choice)
        assert reasoning == "Alternative reasoning format..."

    def test_extract_reasoning_none(self, llm_client):
        """测试没有推理内容的情况."""
        choice = {
            "message": {},
        }
        reasoning = llm_client._extract_reasoning(choice)
        assert reasoning == ""


class TestExtractToolCalls:
    """测试工具调用提取功能."""

    def test_extract_tool_calls_present(self, llm_client):
        """测试提取存在的工具调用."""
        choice = {
            "message": {
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "func1"}},
                    {"id": "call_2", "function": {"name": "func2"}},
                ]
            }
        }
        tool_calls = llm_client._extract_tool_calls(choice)
        assert len(tool_calls) == 2
        assert tool_calls[0]["id"] == "call_1"

    def test_extract_tool_calls_none(self, llm_client):
        """测试没有工具调用的情况."""
        choice = {
            "message": {},
        }
        tool_calls = llm_client._extract_tool_calls(choice)
        assert tool_calls == []

    def test_extract_tool_calls_empty_list(self, llm_client):
        """测试空工具调用列表."""
        choice = {
            "message": {
                "tool_calls": [],
            }
        }
        tool_calls = llm_client._extract_tool_calls(choice)
        assert tool_calls == []


class TestExtractUsage:
    """测试使用量提取功能."""

    def test_extract_usage_complete(self, llm_client):
        """测试提取完整的使用量信息."""
        raw = {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 200,
                "total_tokens": 300,
            }
        }
        usage = llm_client._extract_usage(raw)
        assert usage["prompt_tokens"] == 100
        assert usage["completion_tokens"] == 200
        assert usage["total_tokens"] == 300

    def test_extract_usage_partial(self, llm_client):
        """测试提取部分使用量信息."""
        raw = {
            "usage": {
                "prompt_tokens": 50,
            }
        }
        usage = llm_client._extract_usage(raw)
        assert usage["prompt_tokens"] == 50
        assert usage["completion_tokens"] == 0
        assert usage["total_tokens"] == 0

    def test_extract_usage_missing(self, llm_client):
        """测试没有使用量信息的情况."""
        raw = {}
        usage = llm_client._extract_usage(raw)
        assert usage["prompt_tokens"] == 0
        assert usage["completion_tokens"] == 0
        assert usage["total_tokens"] == 0


class TestParseResponse:
    """测试响应解析功能."""

    def test_parse_normal_response(self, llm_client, sample_openai_response):
        """测试解析正常响应."""
        response = llm_client._parse_response(sample_openai_response)
        
        assert isinstance(response, LLMResponse)
        assert response.content == "Hello, world!"
        assert response.reasoning_content == "Let me think about this..."
        assert response.model == "gpt-4o"
        assert response.total_tokens == 30
        assert response.prompt_tokens == 10
        assert response.completion_tokens == 20

    def test_parse_tool_call_response(self, llm_client, sample_tool_call_response):
        """测试解析工具调用响应."""
        response = llm_client._parse_response(sample_tool_call_response)
        
        assert isinstance(response, LLMResponse)
        assert response.content == ""
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0]["function"]["name"] == "get_weather"
        assert response.total_tokens == 40

    def test_parse_empty_choices(self, llm_client):
        """测试解析空choices的响应."""
        raw = {
            "model": "gpt-4o",
            "choices": [],
        }
        response = llm_client._parse_response(raw)
        
        assert isinstance(response, LLMResponse)
        assert response.content == ""
        # 注意：当前实现在空choices时不会从raw中提取model字段
        # 如果需要此功能，应修改llm_client.py中的_parse_response方法
        assert response.model == ""

    def test_parse_no_choices(self, llm_client):
        """测试解析没有choices字段的响应."""
        raw = {
            "model": "gpt-4o",
        }
        response = llm_client._parse_response(raw)
        
        assert isinstance(response, LLMResponse)
        assert response.content == ""


class TestLLMResponseProperties:
    """测试LLMResponse属性."""

    def test_total_tokens_property(self):
        """测试total_tokens属性."""
        response = LLMResponse(usage={"total_tokens": 100})
        assert response.total_tokens == 100

    def test_prompt_tokens_property(self):
        """测试prompt_tokens属性."""
        response = LLMResponse(usage={"prompt_tokens": 50})
        assert response.prompt_tokens == 50

    def test_completion_tokens_property(self):
        """测试completion_tokens属性."""
        response = LLMResponse(usage={"completion_tokens": 75})
        assert response.completion_tokens == 75

    def test_reasoning_property(self):
        """测试reasoning属性（兼容别名）."""
        response = LLMResponse(reasoning_content="thinking...")
        assert response.reasoning == "thinking..."


class TestCallMethod:
    """测试call方法（需要Mock HTTP客户端）."""

    @pytest.mark.asyncio
    async def test_call_basic(self, llm_client):
        """测试基本LLM调用."""
        mock_response_data = {
            "model": "gpt-4o",
            "choices": [
                {
                    "message": {
                        "content": "Test response",
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }

        with patch.object(llm_client, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            # 关键修复：post必须是AsyncMock，这样await client.post()才能正确工作
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await llm_client.call(
                system_prompt="You are a helpful assistant",
                user_prompt="Hello",
                model="gpt-4o",
            )

            assert isinstance(result, LLMResponse)
            assert result.content == "Test response"
            assert result.model == "gpt-4o"

    @pytest.mark.asyncio
    async def test_call_with_tools(self, llm_client):
        """测试带工具的LLM调用."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {"type": "object"},
                },
            }
        ]

        mock_response_data = {
            "model": "gpt-4o",
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"location": "Beijing"}',
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 15, "completion_tokens": 25, "total_tokens": 40},
        }

        with patch.object(llm_client, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            # 关键修复：post必须是AsyncMock
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await llm_client.call(
                system_prompt="",
                user_prompt="What's the weather?",
                tools=tools,
            )

            assert len(result.tool_calls) == 1

    @pytest.mark.asyncio
    async def test_call_http_error(self, llm_client):
        """测试HTTP错误处理."""
        import httpx

        with patch.object(llm_client, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_response = AsyncMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            error = httpx.HTTPStatusError("Error", request=MagicMock(), response=mock_response)
            mock_client.post.side_effect = error
            mock_get_client.return_value = mock_client

            with pytest.raises(LLMCallException) as exc_info:
                await llm_client.call(
                    system_prompt="",
                    user_prompt="Test",
                )
            
            assert "HTTP 500" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_call_json_decode_error(self, llm_client):
        """测试JSON解码错误处理."""
        with patch.object(llm_client, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
            mock_response.raise_for_status = MagicMock()
            # 关键修复：post必须是AsyncMock
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            with pytest.raises(LLMCallException) as exc_info:
                await llm_client.call(
                    system_prompt="",
                    user_prompt="Test",
                )
            
            assert "Invalid JSON" in str(exc_info.value)


class TestStreamCall:
    """测试流式调用功能."""

    @pytest.mark.asyncio
    async def test_stream_call_basic(self, llm_client):
        """测试基本流式调用."""
        stream_chunks = [
            'data: {"choices": [{"delta": {"content": "Hello"}, "finish_reason": null}]}',
            'data: {"choices": [{"delta": {"content": " world"}, "finish_reason": null}]}',
            'data: [DONE]',
        ]

        with patch.object(llm_client, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            
            # 模拟异步迭代器
            async def mock_iter_lines():
                for chunk in stream_chunks:
                    yield chunk
            
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.aiter_lines = mock_iter_lines
            
            # 模拟异步上下文管理器
            class MockStreamContext:
                async def __aenter__(self):
                    return mock_response
                async def __aexit__(self, *args):
                    pass
            
            # 关键修复：stream方法直接返回上下文管理器，不需要await
            mock_client.stream = MagicMock(return_value=MockStreamContext())
            mock_get_client.return_value = mock_client

            chunks = []
            async for chunk in llm_client.stream_call(
                system_prompt="",
                user_prompt="Test",
            ):
                chunks.append(chunk)

            assert len(chunks) == 2
            assert chunks[0].content == "Hello"
            assert chunks[1].content == " world"

    @pytest.mark.asyncio
    async def test_stream_call_with_reasoning(self, llm_client):
        """测试带推理内容的流式调用."""
        stream_chunks = [
            'data: {"choices": [{"delta": {"reasoning_content": "Thinking..."}, "finish_reason": null}]}',
            'data: [DONE]',
        ]

        with patch.object(llm_client, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            
            async def mock_iter_lines():
                for chunk in stream_chunks:
                    yield chunk
            
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.aiter_lines = mock_iter_lines
            
            class MockStreamContext:
                async def __aenter__(self):
                    return mock_response
                async def __aexit__(self, *args):
                    pass
            
            # 关键修复：stream方法直接返回上下文管理器
            mock_client.stream = MagicMock(return_value=MockStreamContext())
            mock_get_client.return_value = mock_client

            chunks = []
            async for chunk in llm_client.stream_call(
                system_prompt="",
                user_prompt="Test",
            ):
                chunks.append(chunk)

            assert len(chunks) == 1
            assert chunks[0].reasoning_content == "Thinking..."


class TestCallWithFallback:
    """测试带Fallback链的调用."""

    @pytest.mark.asyncio
    async def test_fallback_success_on_first_model(self, llm_client):
        """测试第一个模型成功的情况."""
        mock_response_data = {
            "model": "gpt-4o",
            "choices": [{"message": {"content": "Success"}}],
            "usage": {},
        }

        with patch.object(llm_client, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            # 关键修复：post必须是AsyncMock
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await llm_client.call_with_fallback(
                system_prompt="",
                user_prompt="Test",
                models=["gpt-4o", "claude-sonnet"],
            )

            assert result.content == "Success"

    @pytest.mark.asyncio
    async def test_fallback_chain(self, llm_client):
        """测试Fallback链切换到第二个模型."""
        call_count = [0]

        async def mock_call(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise LLMCallException("First model failed")
            else:
                return LLMResponse(content="Second model success", model="claude-sonnet")

        with patch.object(llm_client, 'call', side_effect=mock_call):
            result = await llm_client.call_with_fallback(
                system_prompt="",
                user_prompt="Test",
                models=["gpt-4o", "claude-sonnet"],
            )

            assert result.content == "Second model success"
            assert result.model == "claude-sonnet"


class TestClientLifecycle:
    """测试客户端生命周期管理."""

    @pytest.mark.asyncio
    async def test_close_client(self, llm_client):
        """测试关闭客户端."""
        # 先获取客户端
        await llm_client._get_client()
        assert llm_client._client is not None
        
        # 关闭
        await llm_client.close()
        assert llm_client._client is None

    @pytest.mark.asyncio
    async def test_async_context_manager(self, llm_client):
        """测试异步上下文管理器."""
        async with llm_client as client:
            assert client is llm_client
        
        # 退出后客户端应被关闭
        assert llm_client._client is None


class TestSemanticCache:
    """测试语义缓存功能."""

    @pytest.mark.asyncio
    async def test_query_cache_hit(self, llm_client):
        """测试缓存命中."""
        mock_response_data = {
            "cached": True,
            "response": "Cached response",
        }

        with patch.object(llm_client, '_get_cache_client') as mock_get_cache_client:
            mock_cache_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            # 关键修复：post必须是AsyncMock
            mock_cache_client.post = AsyncMock(return_value=mock_response)
            mock_get_cache_client.return_value = mock_cache_client

            llm_client.cache_url = "http://cache-service"
            hit, response = await llm_client._query_semantic_cache(
                system_prompt="test",
                user_prompt="test question",
                session_id="session-1",
            )

            assert hit is True
            assert response == "Cached response"

    @pytest.mark.asyncio
    async def test_query_cache_miss(self, llm_client):
        """测试缓存未命中."""
        mock_response_data = {
            "cached": False,
        }

        with patch.object(llm_client, '_get_cache_client') as mock_get_cache_client:
            mock_cache_client = AsyncMock()
            mock_response = AsyncMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_cache_client.post.return_value = mock_response
            mock_get_cache_client.return_value = mock_cache_client

            llm_client.cache_url = "http://cache-service"
            hit, response = await llm_client._query_semantic_cache(
                system_prompt="test",
                user_prompt="test question",
                session_id="session-1",
            )

            assert hit is False
            assert response == ""

    @pytest.mark.asyncio
    async def test_query_cache_disabled(self, llm_client):
        """测试缓存禁用时."""
        llm_client.cache_url = ""
        hit, response = await llm_client._query_semantic_cache(
            system_prompt="test",
            user_prompt="test question",
            session_id="session-1",
        )

        assert hit is False
        assert response == ""

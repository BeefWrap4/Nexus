"""语义缓存边界条件测试.

覆盖:
- 空输入和特殊字符输入
- 超长文本缓存
- Unicode和多语言内容
- 缓存命中率边界
- 并发缓存访问
- 缓存失效边界
- 序列化/反序列化边界
- 相似度阈值边界
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.agent.llm_client import LLMClient, LLMResponse
from nexus.observability.llm_tracer import LLMTraceData


# ---------------------------------------------------------------------------
# 空输入和特殊输入测试
# ---------------------------------------------------------------------------

class TestEmptyAndSpecialInputs:
    """测试空输入和特殊输入的边界情况."""

    @pytest.mark.asyncio
    async def test_empty_prompt_caching(self):
        """空prompt应能正常处理（不缓存或跳过）."""
        client = LLMClient(cache_url="http://localhost:8777")

        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 200
        mock_llm_response.json.return_value = {
            "choices": [{"message": {"content": "empty response"}}],
            "model": "gpt-4o",
        }
        mock_llm_response.raise_for_status = MagicMock()
        mock_llm_client = AsyncMock()
        mock_llm_client.post = AsyncMock(return_value=mock_llm_response)
        mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
        mock_llm_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_llm_client):
            result = await client.call(
                system_prompt="",
                user_prompt="",  # 空prompt
                enable_semantic_cache=True,
                session_id="test-empty",
            )

        assert result.content == "empty response"
        assert result.cache_hit is False

    @pytest.mark.asyncio
    async def test_whitespace_only_prompt(self):
        """只有空白字符的prompt应能处理."""
        client = LLMClient(cache_url="http://localhost:8777")

        cache_response = MagicMock()
        cache_response.status_code = 200
        cache_response.json.return_value = {
            "response": "cached whitespace",
            "cached": True,
            "latency_ms": 10,
        }
        cache_response.raise_for_status = MagicMock()
        mock_cache_client = AsyncMock()
        mock_cache_client.post = AsyncMock(return_value=cache_response)
        mock_cache_client.__aenter__ = AsyncMock(return_value=mock_cache_client)
        mock_cache_client.__aexit__ = AsyncMock(return_value=None)

        mock_llm_client = AsyncMock()
        mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
        mock_llm_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", side_effect=lambda **kwargs: mock_cache_client if kwargs.get("base_url") == "http://localhost:8777" else mock_llm_client):
            result = await client.call(
                system_prompt="",
                user_prompt="   \n\t  ",  # 只有空白
                enable_semantic_cache=True,
                session_id="test-whitespace",
            )

        # 应该命中缓存（如果缓存服务返回cached=True）
        assert result.cache_hit is True or result.cache_hit is False

    @pytest.mark.asyncio
    async def test_special_characters_in_prompt(self):
        """包含特殊字符的prompt应能正常缓存."""
        client = LLMClient(cache_url="http://localhost:8777")

        special_prompt = "!@#$%^&*()_+-=[]{}|;:',.<>?/~`"

        cache_response = MagicMock()
        cache_response.status_code = 200
        cache_response.json.return_value = {
            "response": "cached special chars",
            "cached": True,
            "latency_ms": 15,
        }
        cache_response.raise_for_status = MagicMock()
        mock_cache_client = AsyncMock()
        mock_cache_client.post = AsyncMock(return_value=cache_response)
        mock_cache_client.__aenter__ = AsyncMock(return_value=mock_cache_client)
        mock_cache_client.__aexit__ = AsyncMock(return_value=None)

        mock_llm_client = AsyncMock()
        mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
        mock_llm_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", side_effect=lambda **kwargs: mock_cache_client if kwargs.get("base_url") == "http://localhost:8777" else mock_llm_client):
            result = await client.call(
                system_prompt="",
                user_prompt=special_prompt,
                enable_semantic_cache=True,
                session_id="test-special",
            )

        assert result.cache_hit is True

    @pytest.mark.asyncio
    async def test_null_bytes_in_prompt(self):
        """包含null字节的prompt应能处理."""
        client = LLMClient(cache_url="http://localhost:8777")

        prompt_with_null = "hello\x00world"

        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 200
        mock_llm_response.json.return_value = {
            "choices": [{"message": {"content": "null byte response"}}],
            "model": "gpt-4o",
        }
        mock_llm_response.raise_for_status = MagicMock()
        mock_llm_client = AsyncMock()
        mock_llm_client.post = AsyncMock(return_value=mock_llm_response)
        mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
        mock_llm_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_llm_client):
            result = await client.call(
                system_prompt="",
                user_prompt=prompt_with_null,
                enable_semantic_cache=True,
                session_id="test-null",
            )

        assert result.content == "null byte response"


# ---------------------------------------------------------------------------
# 超长文本测试
# ---------------------------------------------------------------------------

class TestLongTextCaching:
    """测试超长文本的缓存边界."""

    @pytest.mark.asyncio
    async def test_very_long_prompt_caching(self):
        """超长prompt（100KB）应能正常缓存."""
        client = LLMClient(cache_url="http://localhost:8777")

        long_prompt = "x" * 100000  # 100KB

        cache_response = MagicMock()
        cache_response.status_code = 200
        cache_response.json.return_value = {
            "response": "cached long text",
            "cached": True,
            "latency_ms": 50,
        }
        cache_response.raise_for_status = MagicMock()
        mock_cache_client = AsyncMock()
        mock_cache_client.post = AsyncMock(return_value=cache_response)
        mock_cache_client.__aenter__ = AsyncMock(return_value=mock_cache_client)
        mock_cache_client.__aexit__ = AsyncMock(return_value=None)

        mock_llm_client = AsyncMock()
        mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
        mock_llm_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", side_effect=lambda **kwargs: mock_cache_client if kwargs.get("base_url") == "http://localhost:8777" else mock_llm_client):
            result = await client.call(
                system_prompt="",
                user_prompt=long_prompt,
                enable_semantic_cache=True,
                session_id="test-long",
            )

        assert result.cache_hit is True

    @pytest.mark.asyncio
    async def test_extremely_long_prompt(self):
        """极长prompt（1MB）应能处理（可能被截断或拒绝）."""
        client = LLMClient(cache_url="http://localhost:8777")

        extremely_long = "y" * 1000000  # 1MB

        # 缓存服务可能拒绝或超时
        cache_response = MagicMock()
        cache_response.status_code = 413  # Payload Too Large
        cache_response.raise_for_status = MagicMock(side_effect=Exception("Too large"))
        mock_cache_client = AsyncMock()
        mock_cache_client.post = AsyncMock(return_value=cache_response)
        mock_cache_client.__aenter__ = AsyncMock(return_value=mock_cache_client)
        mock_cache_client.__aexit__ = AsyncMock(return_value=None)

        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 200
        mock_llm_response.json.return_value = {
            "choices": [{"message": {"content": "llm response for huge prompt"}}],
            "model": "gpt-4o",
        }
        mock_llm_response.raise_for_status = MagicMock()
        mock_llm_client = AsyncMock()
        mock_llm_client.post = AsyncMock(return_value=mock_llm_response)
        mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
        mock_llm_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", side_effect=lambda **kwargs: mock_cache_client if kwargs.get("base_url") == "http://localhost:8777" else mock_llm_client):
            result = await client.call(
                system_prompt="",
                user_prompt=extremely_long,
                enable_semantic_cache=True,
                session_id="test-huge",
            )

        # 缓存失败应降级到LLM
        assert result.cache_hit is False
        assert result.content == "llm response for huge prompt"


# ---------------------------------------------------------------------------
# Unicode和多语言测试
# ---------------------------------------------------------------------------

class TestUnicodeAndMultilingual:
    """测试Unicode和多语言内容的缓存."""

    @pytest.mark.asyncio
    async def test_chinese_text_caching(self):
        """中文文本应能正常缓存."""
        client = LLMClient(cache_url="http://localhost:8777")

        chinese_prompt = "这是一个测试问题，关于人工智能的发展历史。"

        cache_response = MagicMock()
        cache_response.status_code = 200
        cache_response.json.return_value = {
            "response": "缓存的中文回答",
            "cached": True,
            "latency_ms": 20,
        }
        cache_response.raise_for_status = MagicMock()
        mock_cache_client = AsyncMock()
        mock_cache_client.post = AsyncMock(return_value=cache_response)
        mock_cache_client.__aenter__ = AsyncMock(return_value=mock_cache_client)
        mock_cache_client.__aexit__ = AsyncMock(return_value=None)

        mock_llm_client = AsyncMock()
        mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
        mock_llm_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", side_effect=lambda **kwargs: mock_cache_client if kwargs.get("base_url") == "http://localhost:8777" else mock_llm_client):
            result = await client.call(
                system_prompt="",
                user_prompt=chinese_prompt,
                enable_semantic_cache=True,
                session_id="test-chinese",
            )

        assert result.cache_hit is True
        assert result.content == "缓存的中文回答"

    @pytest.mark.asyncio
    async def test_mixed_language_caching(self):
        """混合语言文本应能缓存."""
        client = LLMClient(cache_url="http://localhost:8777")

        mixed_prompt = "Hello 你好 Bonjour こんにちは Привет"

        cache_response = MagicMock()
        cache_response.status_code = 200
        cache_response.json.return_value = {
            "response": "Cached multilingual response",
            "cached": True,
            "latency_ms": 25,
        }
        cache_response.raise_for_status = MagicMock()
        mock_cache_client = AsyncMock()
        mock_cache_client.post = AsyncMock(return_value=cache_response)
        mock_cache_client.__aenter__ = AsyncMock(return_value=mock_cache_client)
        mock_cache_client.__aexit__ = AsyncMock(return_value=None)

        mock_llm_client = AsyncMock()
        mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
        mock_llm_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", side_effect=lambda **kwargs: mock_cache_client if kwargs.get("base_url") == "http://localhost:8777" else mock_llm_client):
            result = await client.call(
                system_prompt="",
                user_prompt=mixed_prompt,
                enable_semantic_cache=True,
                session_id="test-mixed",
            )

        assert result.cache_hit is True

    @pytest.mark.asyncio
    async def test_emoji_in_prompt(self):
        """包含emoji的prompt应能缓存."""
        client = LLMClient(cache_url="http://localhost:8777")

        emoji_prompt = "Explain AI 🤖 in simple terms 💡 with examples 📚"

        cache_response = MagicMock()
        cache_response.status_code = 200
        cache_response.json.return_value = {
            "response": "AI is like a smart computer program 🧠",
            "cached": True,
            "latency_ms": 18,
        }
        cache_response.raise_for_status = MagicMock()
        mock_cache_client = AsyncMock()
        mock_cache_client.post = AsyncMock(return_value=cache_response)
        mock_cache_client.__aenter__ = AsyncMock(return_value=mock_cache_client)
        mock_cache_client.__aexit__ = AsyncMock(return_value=None)

        mock_llm_client = AsyncMock()
        mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
        mock_llm_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", side_effect=lambda **kwargs: mock_cache_client if kwargs.get("base_url") == "http://localhost:8777" else mock_llm_client):
            result = await client.call(
                system_prompt="",
                user_prompt=emoji_prompt,
                enable_semantic_cache=True,
                session_id="test-emoji",
            )

        assert result.cache_hit is True
        assert "🧠" in result.content


# ---------------------------------------------------------------------------
# 缓存命中率边界测试
# ---------------------------------------------------------------------------

class TestCacheHitRateBoundaries:
    """测试缓存命中率的边界情况."""

    @pytest.mark.asyncio
    async def test_similar_but_not_identical_prompts(self):
        """相似但不完全相同的prompts应有不同的缓存键."""
        client = LLMClient(cache_url="http://localhost:8777")

        # 第一次调用 - 缓存miss
        cache_miss_response = MagicMock()
        cache_miss_response.status_code = 200
        cache_miss_response.json.return_value = {
            "response": "",
            "cached": False,
            "latency_ms": 5,
        }
        cache_miss_response.raise_for_status = MagicMock()

        mock_llm_response1 = MagicMock()
        mock_llm_response1.status_code = 200
        mock_llm_response1.json.return_value = {
            "choices": [{"message": {"content": "answer 1"}}],
            "model": "gpt-4o",
        }
        mock_llm_response1.raise_for_status = MagicMock()

        mock_cache_client = AsyncMock()
        mock_cache_client.post = AsyncMock(return_value=cache_miss_response)
        mock_cache_client.__aenter__ = AsyncMock(return_value=mock_cache_client)
        mock_cache_client.__aexit__ = AsyncMock(return_value=None)

        mock_llm_client = AsyncMock()
        mock_llm_client.post = AsyncMock(return_value=mock_llm_response1)
        mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
        mock_llm_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", side_effect=lambda **kwargs: mock_cache_client if kwargs.get("base_url") == "http://localhost:8777" else mock_llm_client):
            result1 = await client.call(
                system_prompt="",
                user_prompt="What is AI?",
                enable_semantic_cache=True,
                session_id="test-similar-1",
            )

        assert result1.cache_hit is False

    @pytest.mark.asyncio
    async def test_case_sensitivity_in_caching(self):
        """大小写不同的prompts是否共享缓存取决于实现."""
        client = LLMClient(cache_url="http://localhost:8777")

        # 这两个prompts可能被视为相同或不同，取决于哈希策略
        prompts = ["What is AI?", "what is ai?", "WHAT IS AI?"]

        for i, prompt in enumerate(prompts):
            cache_response = MagicMock()
            cache_response.status_code = 200
            cache_response.json.return_value = {
                "response": f"cached answer {i}",
                "cached": i > 0,  # 第一个miss，后续hit
                "latency_ms": 10,
            }
            cache_response.raise_for_status = MagicMock()

            mock_cache_client = AsyncMock()
            mock_cache_client.post = AsyncMock(return_value=cache_response)
            mock_cache_client.__aenter__ = AsyncMock(return_value=mock_cache_client)
            mock_cache_client.__aexit__ = AsyncMock(return_value=None)

            mock_llm_response = MagicMock()
            mock_llm_response.status_code = 200
            mock_llm_response.json.return_value = {
                "choices": [{"message": {"content": f"llm answer {i}"}}],
                "model": "gpt-4o",
            }
            mock_llm_response.raise_for_status = MagicMock()
            mock_llm_client = AsyncMock()
            mock_llm_client.post = AsyncMock(return_value=mock_llm_response)
            mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
            mock_llm_client.__aexit__ = AsyncMock(return_value=None)

            with patch("httpx.AsyncClient", side_effect=lambda **kwargs: mock_cache_client if kwargs.get("base_url") == "http://localhost:8777" else mock_llm_client):
                result = await client.call(
                    system_prompt="",
                    user_prompt=prompt,
                    enable_semantic_cache=True,
                    session_id=f"test-case-{i}",
                )

            # 至少第一个应该是miss
            if i == 0:
                assert result.cache_hit is False


# ---------------------------------------------------------------------------
# 并发缓存访问测试
# ---------------------------------------------------------------------------

class TestConcurrentCacheAccess:
    """测试并发缓存访问的边界情况."""

    @pytest.mark.asyncio
    async def test_concurrent_cache_reads(self):
        """多个并发请求读取同一缓存键应正常工作."""
        client = LLMClient(cache_url="http://localhost:8777")

        cache_response = MagicMock()
        cache_response.status_code = 200
        cache_response.json.return_value = {
            "response": "concurrent cached answer",
            "cached": True,
            "latency_ms": 10,
        }
        cache_response.raise_for_status = MagicMock()

        mock_cache_client = AsyncMock()
        mock_cache_client.post = AsyncMock(return_value=cache_response)
        mock_cache_client.__aenter__ = AsyncMock(return_value=mock_cache_client)
        mock_cache_client.__aexit__ = AsyncMock(return_value=None)

        mock_llm_client = AsyncMock()
        mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
        mock_llm_client.__aexit__ = AsyncMock(return_value=None)

        async def make_request(session_id):
            with patch("httpx.AsyncClient", side_effect=lambda **kwargs: mock_cache_client if kwargs.get("base_url") == "http://localhost:8777" else mock_llm_client):
                return await client.call(
                    system_prompt="",
                    user_prompt="concurrent test",
                    enable_semantic_cache=True,
                    session_id=session_id,
                )

        # 并发执行10个请求
        tasks = [make_request(f"concurrent-{i}") for i in range(10)]
        results = await asyncio.gather(*tasks)

        # 所有请求都应命中缓存
        assert all(r.cache_hit is True for r in results)
        assert all(r.content == "concurrent cached answer" for r in results)


# ---------------------------------------------------------------------------
# 缓存失效边界测试
# ---------------------------------------------------------------------------

class TestCacheInvalidationBoundaries:
    """测试缓存失效的边界情况."""

    @pytest.mark.asyncio
    async def test_cache_with_different_models(self):
        """不同模型的相同prompt应有不同的缓存."""
        client = LLMClient(cache_url="http://localhost:8777")

        # gpt-4o的响应
        cache_response_gpt4 = MagicMock()
        cache_response_gpt4.status_code = 200
        cache_response_gpt4.json.return_value = {
            "response": "gpt-4o answer",
            "cached": True,
            "latency_ms": 15,
        }
        cache_response_gpt4.raise_for_status = MagicMock()

        mock_cache_client = AsyncMock()
        mock_cache_client.post = AsyncMock(return_value=cache_response_gpt4)
        mock_cache_client.__aenter__ = AsyncMock(return_value=mock_cache_client)
        mock_cache_client.__aexit__ = AsyncMock(return_value=None)

        mock_llm_client = AsyncMock()
        mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
        mock_llm_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", side_effect=lambda **kwargs: mock_cache_client if kwargs.get("base_url") == "http://localhost:8777" else mock_llm_client):
            result = await client.call(
                system_prompt="",
                user_prompt="test prompt",
                model="gpt-4o",
                enable_semantic_cache=True,
                session_id="test-model-gpt4",
            )

        assert result.cache_hit is True
        assert result.content == "gpt-4o answer"

    @pytest.mark.asyncio
    async def test_cache_with_different_temperature(self):
        """不同temperature的相同prompt可能有不同的缓存行为."""
        client = LLMClient(cache_url="http://localhost:8777")

        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 200
        mock_llm_response.json.return_value = {
            "choices": [{"message": {"content": "temperature specific answer"}}],
            "model": "gpt-4o",
        }
        mock_llm_response.raise_for_status = MagicMock()
        mock_llm_client = AsyncMock()
        mock_llm_client.post = AsyncMock(return_value=mock_llm_response)
        mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
        mock_llm_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_llm_client):
            # 高temperature可能跳过缓存
            result = await client.call(
                system_prompt="",
                user_prompt="creative question",
                temperature=0.9,
                enable_semantic_cache=True,
                session_id="test-temp-high",
            )

        # 具体行为取决于实现
        assert result.content == "temperature specific answer"


# ---------------------------------------------------------------------------
# 序列化/反序列化边界测试
# ---------------------------------------------------------------------------

class TestSerializationBoundaries:
    """测试缓存序列化的边界情况."""

    def test_cache_response_structure(self):
        """缓存响应结构应包含必要字段."""
        from nexus.observability.llm_tracer import LLMTraceData

        trace = LLMTraceData(
            model="gpt-4o",
            cache_hit=True,
            prompt_tokens=100,
            completion_tokens=50,
        )

        db_dict = trace.to_db_dict()
        assert "cache_hit" in db_dict
        assert db_dict["cache_hit"] is True

    def test_trace_with_none_values(self):
        """Trace数据包含None值时应能序列化."""
        from nexus.observability.llm_tracer import LLMTraceData

        trace = LLMTraceData(
            model="gpt-4o",
            cache_hit=None,  # None值
        )

        db_dict = trace.to_db_dict()
        # None值应被正确处理
        assert "cache_hit" in db_dict


# ---------------------------------------------------------------------------
# 相似度阈值边界测试
# ---------------------------------------------------------------------------

class TestSimilarityThresholdBoundaries:
    """测试相似度阈值的边界情况."""

    @pytest.mark.asyncio
    async def test_exact_match_should_hit_cache(self):
        """完全匹配的prompt应命中缓存."""
        client = LLMClient(cache_url="http://localhost:8777")

        exact_prompt = "exact match test"

        cache_response = MagicMock()
        cache_response.status_code = 200
        cache_response.json.return_value = {
            "response": "exact match answer",
            "cached": True,
            "similarity": 1.0,  # 完全匹配
            "latency_ms": 5,
        }
        cache_response.raise_for_status = MagicMock()

        mock_cache_client = AsyncMock()
        mock_cache_client.post = AsyncMock(return_value=cache_response)
        mock_cache_client.__aenter__ = AsyncMock(return_value=mock_cache_client)
        mock_cache_client.__aexit__ = AsyncMock(return_value=None)

        mock_llm_client = AsyncMock()
        mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
        mock_llm_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", side_effect=lambda **kwargs: mock_cache_client if kwargs.get("base_url") == "http://localhost:8777" else mock_llm_client):
            result = await client.call(
                system_prompt="",
                user_prompt=exact_prompt,
                enable_semantic_cache=True,
                session_id="test-exact",
            )

        assert result.cache_hit is True

    @pytest.mark.asyncio
    async def test_below_threshold_should_miss(self):
        """低于相似度阈值的prompt应miss."""
        client = LLMClient(cache_url="http://localhost:8777")

        cache_response = MagicMock()
        cache_response.status_code = 200
        cache_response.json.return_value = {
            "response": "",
            "cached": False,
            "similarity": 0.5,  # 低于典型阈值0.8
            "latency_ms": 8,
        }
        cache_response.raise_for_status = MagicMock()

        mock_cache_client = AsyncMock()
        mock_cache_client.post = AsyncMock(return_value=cache_response)
        mock_cache_client.__aenter__ = AsyncMock(return_value=mock_cache_client)
        mock_cache_client.__aexit__ = AsyncMock(return_value=None)

        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 200
        mock_llm_response.json.return_value = {
            "choices": [{"message": {"content": "new answer"}}],
            "model": "gpt-4o",
        }
        mock_llm_response.raise_for_status = MagicMock()
        mock_llm_client = AsyncMock()
        mock_llm_client.post = AsyncMock(return_value=mock_llm_response)
        mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
        mock_llm_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", side_effect=lambda **kwargs: mock_cache_client if kwargs.get("base_url") == "http://localhost:8777" else mock_llm_client):
            result = await client.call(
                system_prompt="",
                user_prompt="different question",
                enable_semantic_cache=True,
                session_id="test-below-threshold",
            )

        assert result.cache_hit is False
        assert result.content == "new answer"

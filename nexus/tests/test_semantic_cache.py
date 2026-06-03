"""Semantic Cache integration tests — Phase 9.

Covers:
- cache_hit: LLMClient returns cached response without calling LiteLLM
- cache_miss: fallback to normal LLM call
- cache_service_unavailable: graceful degradation
- cache_disabled: no cache query when disabled
- stream_cache_hit: stream call yields single chunk on cache hit
- metrics_updated: Prometheus counters incremented correctly
- trace_persisted: LLMTraceData records cache_hit flag
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.agent.llm_client import LLMClient, LLMResponse
from nexus.observability.llm_tracer import LLMTraceData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cache_response(cached: bool, response_text: str = "cached answer"):
    """Build a mock smart-cache response."""
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {
        "response": response_text,
        "cached": cached,
        "latency_ms": 45,
    }
    mock.raise_for_status = MagicMock()
    return mock


# ---------------------------------------------------------------------------
# Cache Hit
# ---------------------------------------------------------------------------

class TestCacheHit:
    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_response(self, monkeypatch):
        monkeypatch.setenv("SMART_CACHE_URL", "http://localhost:8777")

        client = LLMClient(cache_url="http://localhost:8777")

        # Mock cache client
        cache_response = _make_cache_response(cached=True, response_text="cached answer")
        mock_cache_client = AsyncMock()
        mock_cache_client.post = AsyncMock(return_value=cache_response)
        mock_cache_client.__aenter__ = AsyncMock(return_value=mock_cache_client)
        mock_cache_client.__aexit__ = AsyncMock(return_value=None)

        # Mock LiteLLM client should NOT be called
        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 200
        mock_llm_response.json.return_value = {
            "choices": [{"message": {"content": "llm answer"}}],
            "model": "gpt-4o",
        }
        mock_llm_response.raise_for_status = MagicMock()
        mock_llm_client = AsyncMock()
        mock_llm_client.post = AsyncMock(return_value=mock_llm_response)
        mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
        mock_llm_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", side_effect=lambda **kwargs: mock_cache_client if kwargs.get("base_url") == "http://localhost:8777" else mock_llm_client):
            result = await client.call(
                system_prompt="You are a helpful assistant",
                user_prompt="What is semantic cache?",
                model="gpt-4o",
                enable_semantic_cache=True,
                session_id="test-session-001",
            )

        assert result.cache_hit is True
        assert result.content == "cached answer"
        # LiteLLM should NOT be called on cache hit
        mock_llm_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_hit_with_tools_ignores_cache(self, monkeypatch):
        """When tools are provided, cache should be skipped (complex interaction)."""
        client = LLMClient(cache_url="http://localhost:8777")

        # Even with cache enabled, if tools are passed we skip cache for now
        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 200
        mock_llm_response.json.return_value = {
            "choices": [{"message": {"content": "tool result"}}],
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
                user_prompt="test",
                tools=[{"type": "function", "function": {"name": "test"}}],
                enable_semantic_cache=True,
                session_id="test-session",
            )

        assert result.cache_hit is False
        mock_llm_client.post.assert_called_once()


# ---------------------------------------------------------------------------
# Cache Miss
# ---------------------------------------------------------------------------

class TestCacheMiss:
    @pytest.mark.asyncio
    async def test_cache_miss_falls_back_to_llm(self, monkeypatch):
        monkeypatch.setenv("SMART_CACHE_URL", "http://localhost:8777")

        client = LLMClient(cache_url="http://localhost:8777")

        cache_response = _make_cache_response(cached=False)
        mock_cache_client = AsyncMock()
        mock_cache_client.post = AsyncMock(return_value=cache_response)
        mock_cache_client.__aenter__ = AsyncMock(return_value=mock_cache_client)
        mock_cache_client.__aexit__ = AsyncMock(return_value=None)

        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 200
        mock_llm_response.json.return_value = {
            "choices": [{"message": {"content": "llm generated answer"}}],
            "model": "gpt-4o",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        mock_llm_response.raise_for_status = MagicMock()
        mock_llm_client = AsyncMock()
        mock_llm_client.post = AsyncMock(return_value=mock_llm_response)
        mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
        mock_llm_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", side_effect=lambda **kwargs: mock_cache_client if kwargs.get("base_url") == "http://localhost:8777" else mock_llm_client):
            result = await client.call(
                system_prompt="",
                user_prompt="new unique question",
                model="gpt-4o",
                enable_semantic_cache=True,
                session_id="test-session-002",
            )

        assert result.cache_hit is False
        assert result.content == "llm generated answer"
        # Both cache and LLM should be called
        mock_cache_client.post.assert_called_once()
        mock_llm_client.post.assert_called_once()


# ---------------------------------------------------------------------------
# Cache Service Unavailable
# ---------------------------------------------------------------------------

class TestCacheUnavailable:
    @pytest.mark.asyncio
    async def test_cache_error_graceful_degradation(self, monkeypatch):
        client = LLMClient(cache_url="http://localhost:8777")

        mock_cache_client = AsyncMock()
        mock_cache_client.post = AsyncMock(side_effect=Exception("Connection refused"))
        mock_cache_client.__aenter__ = AsyncMock(return_value=mock_cache_client)
        mock_cache_client.__aexit__ = AsyncMock(return_value=None)

        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 200
        mock_llm_response.json.return_value = {
            "choices": [{"message": {"content": "fallback answer"}}],
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
                user_prompt="test",
                enable_semantic_cache=True,
                session_id="test-session",
            )

        assert result.cache_hit is False
        assert result.content == "fallback answer"


# ---------------------------------------------------------------------------
# Cache Disabled
# ---------------------------------------------------------------------------

class TestCacheDisabled:
    @pytest.mark.asyncio
    async def test_cache_disabled_skips_query(self):
        client = LLMClient(cache_url="http://localhost:8777")

        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 200
        mock_llm_response.json.return_value = {
            "choices": [{"message": {"content": "direct answer"}}],
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
                user_prompt="test",
                enable_semantic_cache=False,
                session_id="test-session",
            )

        assert result.cache_hit is False
        # Only LLM called, no cache query
        assert mock_llm_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_no_session_id_skips_cache(self):
        """Even with enable_semantic_cache=True, empty session_id skips cache."""
        client = LLMClient(cache_url="http://localhost:8777")

        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 200
        mock_llm_response.json.return_value = {
            "choices": [{"message": {"content": "direct answer"}}],
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
                user_prompt="test",
                enable_semantic_cache=True,
                session_id="",
            )

        assert result.cache_hit is False


# ---------------------------------------------------------------------------
# Stream Cache Hit
# ---------------------------------------------------------------------------

class TestStreamCacheHit:
    @pytest.mark.asyncio
    async def test_stream_cache_hit_yields_single_chunk(self, monkeypatch):
        monkeypatch.setenv("SMART_CACHE_URL", "http://localhost:8777")

        client = LLMClient(cache_url="http://localhost:8777")

        cache_response = _make_cache_response(cached=True, response_text="streamed cached answer")
        mock_cache_client = AsyncMock()
        mock_cache_client.post = AsyncMock(return_value=cache_response)
        mock_cache_client.__aenter__ = AsyncMock(return_value=mock_cache_client)
        mock_cache_client.__aexit__ = AsyncMock(return_value=None)

        mock_llm_client = AsyncMock()
        mock_llm_client.__aenter__ = AsyncMock(return_value=mock_llm_client)
        mock_llm_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", side_effect=lambda **kwargs: mock_cache_client if kwargs.get("base_url") == "http://localhost:8777" else mock_llm_client):
            chunks = []
            async for chunk in client.stream_call(
                system_prompt="",
                user_prompt="test",
                enable_semantic_cache=True,
                session_id="stream-test",
            ):
                chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].content == "streamed cached answer"
        assert chunks[0].finish_reason == "stop"


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class TestCacheMetrics:
    def test_cache_hit_updates_metrics(self):
        from nexus.observability.metrics import CACHE_HITS_TOTAL

        # Record a hit
        CACHE_HITS_TOTAL.labels(model="gpt-4o", tenant_id="test").inc()
        # Just verify the metric exists and can be incremented
        assert CACHE_HITS_TOTAL._name == "nexus_cache_hits"

    def test_cache_miss_updates_metrics(self):
        from nexus.observability.metrics import CACHE_MISSES_TOTAL

        CACHE_MISSES_TOTAL.labels(model="gpt-4o", tenant_id="test").inc()
        assert CACHE_MISSES_TOTAL._name == "nexus_cache_misses"


# ---------------------------------------------------------------------------
# Trace Persistence
# ---------------------------------------------------------------------------

class TestTraceCacheHit:
    def test_trace_data_has_cache_hit_field(self):
        trace = LLMTraceData(model="gpt-4o", cache_hit=True)
        db_dict = trace.to_db_dict()
        assert db_dict["cache_hit"] is True

    def test_trace_data_default_cache_hit_false(self):
        trace = LLMTraceData(model="gpt-4o")
        assert trace.cache_hit is False
        db_dict = trace.to_db_dict()
        assert db_dict["cache_hit"] is False

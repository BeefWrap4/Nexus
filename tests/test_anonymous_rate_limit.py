"""Verify anonymous traffic is rate-limited per IP, before auth.

The RateLimiter in get_current_user only runs after auth succeeds.
A pre-auth anonymous DoS protection must run BEFORE auth, keying on
client IP, and applying to ALL paths (including /health, /metrics).
"""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _build_mock_rate_limiter(allowed_sequence):
    """Return a (limiter_mock, check_mock) pair that mirrors the real
    RateLimiter.check_rate_limit contract:
      - If under limit: returns a dict {"allowed": True, ...}
      - If over limit:  raises HTTPException(429)
    """
    call_count = {"n": 0}

    async def _check(api_key, limit, window=60):  # noqa: ARG001
        i = call_count["n"]
        call_count["n"] += 1
        if i >= len(allowed_sequence):
            return {"allowed": True, "remaining": 0, "reset_at": 0.0}
        allowed = allowed_sequence[i]
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": "60"},
            )
        return {"allowed": True, "remaining": 99, "reset_at": 0.0}

    check_mock = AsyncMock(side_effect=_check)
    limiter_mock = MagicMock()
    limiter_mock.check_rate_limit = check_mock
    return limiter_mock, check_mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_anonymous_request_above_limit_returns_429():
    """N anonymous requests in 1 minute → 429 by the (limit+1)th.

    The middleware is wired such that once the per-IP check returns
    False, the next request is rejected with 429. We test the boundary:
    exactly `limit` successes followed by a 429.
    """
    limit = 50
    limiter_mock, check_mock = _build_mock_rate_limiter(
        [True] * limit + [False] * 5
    )

    with patch(
        "nexus.security.anonymous_rate_limit._get_rate_limiter",
        return_value=limiter_mock,
    ):
        from nexus.api.main import app
        client = TestClient(app)
        statuses = []
        for _ in range(limit + 1):
            r = client.get(
                "/api/v1/workflows",
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
            statuses.append(r.status_code)
        # Should hit 429 at or before the (limit+1)th request
        assert 429 in statuses, (
            f"Never returned 429. Statuses seen: {sorted(set(statuses))}"
        )
        # The 429 should be the LAST call (check returns False on
        # the (limit+1)th invocation).
        assert statuses[limit] == 429


def test_health_endpoint_also_rate_limited():
    """/health is not exempt from anonymous DoS protection."""
    limit = 30
    limiter_mock, check_mock = _build_mock_rate_limiter(
        [True] * limit + [False] * 5
    )

    with patch(
        "nexus.security.anonymous_rate_limit._get_rate_limiter",
        return_value=limiter_mock,
    ):
        from nexus.api.main import app
        client = TestClient(app)
        statuses = []
        for _ in range(limit + 1):
            r = client.get(
                "/health",
                headers={"X-Forwarded-For": "5.6.7.8"},
            )
            statuses.append(r.status_code)
        assert 429 in statuses, (
            f"Never returned 429 on /health. Statuses seen: {sorted(set(statuses))}"
        )
        assert statuses[limit] == 429


def test_different_ips_have_independent_buckets():
    """Rate limit is per-IP, not global — each IP gets its own bucket."""
    # Each call to check_rate_limit returns True (always allow).
    # We capture the (key) argument to verify IP separation.
    seen_keys = []

    async def _capture(api_key, limit, window=60):  # noqa: ARG001
        seen_keys.append(api_key)
        return {"allowed": True, "remaining": 99, "reset_at": 0.0}

    limiter_mock = MagicMock()
    limiter_mock.check_rate_limit = _capture

    with patch(
        "nexus.security.anonymous_rate_limit._get_rate_limiter",
        return_value=limiter_mock,
    ):
        from nexus.api.main import app
        client = TestClient(app)
        # IP A makes 20 requests
        for _ in range(20):
            r = client.get("/health", headers={"X-Forwarded-For": "9.9.9.9"})
            assert r.status_code != 429
        # IP B makes 20 requests
        for _ in range(20):
            r = client.get("/health", headers={"X-Forwarded-For": "9.9.9.10"})
            assert r.status_code != 429
        # IP A made 20 calls, IP B made 20 calls — total 40
        assert len(seen_keys) == 40
        # Keys are namespaced by IP — IP A and IP B should have separate
        # keys.
        keys_a = {k for k in seen_keys if "9.9.9.9" in k}
        keys_b = {k for k in seen_keys if "9.9.9.10" in k}
        assert len(keys_a) >= 1 and len(keys_b) >= 1, (
            f"Expected separate keys per IP. Saw: {set(seen_keys)}"
        )
        assert keys_a.isdisjoint(keys_b), "IP A and IP B should not share a key"


def test_middleware_uses_x_forwarded_for_first_hop():
    """X-Forwarded-For: a, b, c → key uses 'a' (the original client)."""
    seen_keys = []

    async def _capture(api_key, limit, window=60):  # noqa: ARG001
        seen_keys.append(api_key)
        return {"allowed": True, "remaining": 99, "reset_at": 0.0}

    limiter_mock = MagicMock()
    limiter_mock.check_rate_limit = _capture

    with patch(
        "nexus.security.anonymous_rate_limit._get_rate_limiter",
        return_value=limiter_mock,
    ):
        from nexus.api.main import app
        client = TestClient(app)
        r = client.get(
            "/health",
            headers={"X-Forwarded-For": "1.1.1.1, 10.0.0.1, 10.0.0.2"},
        )
        assert r.status_code != 429
        # First entry of X-Forwarded-For is the original client (1.1.1.1)
        assert any("1.1.1.1" in k for k in seen_keys), (
            f"Expected key to contain '1.1.1.1', got: {seen_keys}"
        )
        # Not the last hop
        assert not any("10.0.0.2" in k for k in seen_keys)

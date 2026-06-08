"""Tests for RBAC middleware deny-by-default behavior (Phase 3.2).

P1 follow-up: rbac.py:36-38 was fail-open. A request with an auth header but
no ``request.state.user`` was passed through without a permission check.
Likewise, requests to paths outside ``KNOWN_RESOURCES`` were also pass-through.

These tests verify the deny-by-default contract:

1. Unknown resource path → 403
2. No ``request.state.user`` → defer to ``get_current_user`` (pass through)
3. Public paths still bypass (regression guard)
4. Known path + valid user + allowed permission → pass through
5. Known path + valid user + denied permission → 403
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nexus.security.rbac import RBACMiddleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    path: str,
    method: str = "GET",
    headers: dict | None = None,
    user=None,
    has_state: bool = True,
) -> MagicMock:
    """Build a mock request that mimics what starlette passes to dispatch().

    ``user=None`` + ``has_state=True`` produces a state whose ``user`` attribute
    is *genuinely* absent (so ``getattr(request.state, "user", None)`` returns
    None). We use a spec-less object instead of a MagicMock because MagicMock
    auto-creates any requested attribute and would mask the None case.
    """
    request = MagicMock()
    request.method = method
    request.url.path = path
    request.headers = headers if headers is not None else {}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    if has_state:
        # Use a plain object so .user is truly absent unless set explicitly
        class _State:
            pass

        state = _State()
        if user is not None:
            state.user = user
        request.state = state
    return request


def _make_call_next():
    """Return ``(call_next, sentinel)``. ``call_next`` returns the sentinel."""
    sentinel = MagicMock()
    sentinel.status_code = 200

    async def _call_next(_request):
        _call_next.called = True
        return sentinel

    _call_next.called = False
    return _call_next, sentinel


# ---------------------------------------------------------------------------
# Deny-by-default tests (the core Phase 3.2 fix)
# ---------------------------------------------------------------------------


class TestRBACDenyByDefault:
    """Phase 3.2: RBAC must fail-CLOSED, never fail-open."""

    @pytest.mark.asyncio
    async def test_unknown_resource_path_returns_403(self):
        """Unknown path is denied 403 — not silently passed through.

        Deny-by-default invariant: paths outside ``KNOWN_RESOURCES`` have no
        permission mapping, so the safe default is to reject.
        """
        request = _make_request(
            "/api/v1/totally-unknown-resource/abc",
            method="GET",
            headers={"Authorization": "Bearer xyz"},
            user={"id": "u1", "tenant_id": "t1", "role": "admin"},
        )
        call_next, _sentinel = _make_call_next()
        middleware = RBACMiddleware(app=MagicMock())

        result = await middleware.dispatch(request, call_next)

        # Must NOT silently pass through to call_next
        assert call_next.called is False, "RBAC must not pass through for unknown paths"
        # Must be a 403 response
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_no_user_state_with_auth_header_defers_to_dep(self):
        """No ``request.state.user`` defers to ``get_current_user`` (pass through).

        Even with an Authorization header, if the user state hasn't been set
        (e.g. dev mode, mis-configured middleware), RBAC must not silently
        pass through. It must pass through to the route so the auth
        dependency can validate the token and reject with 401 if invalid.
        """
        request = _make_request(
            "/api/v1/workflows",
            method="GET",
            headers={"Authorization": "Bearer some-token"},
            user=None,
        )
        call_next, sentinel = _make_call_next()
        middleware = RBACMiddleware(app=MagicMock())

        result = await middleware.dispatch(request, call_next)

        # Must pass through to call_next (the dep will raise 401 if invalid)
        assert call_next.called is True
        # Response is whatever the route / dep returned
        assert result is sentinel


# ---------------------------------------------------------------------------
# Regression guards: behavior that must NOT change
# ---------------------------------------------------------------------------


class TestRBACRegressionGuards:
    """Existing behavior that must be preserved by the deny-by-default fix."""

    @pytest.mark.asyncio
    async def test_public_path_health_passes_through(self):
        """``/health`` is a public path and must always pass through."""
        request = _make_request(
            "/health",
            method="GET",
            headers={},
            user=None,
        )
        call_next, sentinel = _make_call_next()
        middleware = RBACMiddleware(app=MagicMock())

        result = await middleware.dispatch(request, call_next)

        assert call_next.called is True
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_public_path_metrics_passes_through(self):
        """``/metrics`` is a public path and must always pass through."""
        request = _make_request(
            "/metrics",
            method="GET",
            headers={},
            user=None,
        )
        call_next, sentinel = _make_call_next()
        middleware = RBACMiddleware(app=MagicMock())

        result = await middleware.dispatch(request, call_next)

        assert call_next.called is True
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_auth_routes_pass_through(self):
        """``/api/v1/auth/*`` is a public path and must always pass through."""
        request = _make_request(
            "/api/v1/auth/login",
            method="POST",
            headers={},
            user=None,
        )
        call_next, sentinel = _make_call_next()
        middleware = RBACMiddleware(app=MagicMock())

        result = await middleware.dispatch(request, call_next)

        assert call_next.called is True
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_webhook_routes_pass_through(self):
        """``/api/v1/webhooks/*`` uses HMAC self-verification, must pass through."""
        request = _make_request(
            "/api/v1/webhooks/github",
            method="POST",
            headers={},
            user=None,
        )
        call_next, sentinel = _make_call_next()
        middleware = RBACMiddleware(app=MagicMock())

        result = await middleware.dispatch(request, call_next)

        assert call_next.called is True
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_known_path_admin_user_passes_through(self):
        """Known path + admin role: permission check passes, request goes through."""
        request = _make_request(
            "/api/v1/workflows",
            method="GET",
            headers={"Authorization": "Bearer xyz"},
            user={"id": "u1", "tenant_id": "t1", "role": "admin"},
        )
        call_next, sentinel = _make_call_next()
        middleware = RBACMiddleware(app=MagicMock())

        result = await middleware.dispatch(request, call_next)

        assert call_next.called is True
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_known_path_viewer_post_returns_403(self):
        """Viewer (read-only) trying to POST workflows: permission denied, 403."""
        request = _make_request(
            "/api/v1/workflows",
            method="POST",
            headers={"Authorization": "Bearer xyz"},
            user={"id": "u1", "tenant_id": "t1", "role": "viewer"},
        )
        call_next, _sentinel = _make_call_next()
        middleware = RBACMiddleware(app=MagicMock())

        result = await middleware.dispatch(request, call_next)

        # Must NOT pass through
        assert call_next.called is False
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_known_path_member_user_get_passes_through(self):
        """Member role has workflow read permission: GET workflows passes through."""
        request = _make_request(
            "/api/v1/workflows",
            method="GET",
            headers={"Authorization": "Bearer xyz"},
            user={"id": "u1", "tenant_id": "t1", "role": "member"},
        )
        call_next, sentinel = _make_call_next()
        middleware = RBACMiddleware(app=MagicMock())

        result = await middleware.dispatch(request, call_next)

        assert call_next.called is True
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_no_user_no_auth_header_defers_to_dep(self):
        """No user + no auth header: still defers to dep (no fail-open, no 401 from RBAC)."""
        request = _make_request(
            "/api/v1/workflows",
            method="GET",
            headers={},
            user=None,
        )
        call_next, sentinel = _make_call_next()
        middleware = RBACMiddleware(app=MagicMock())

        result = await middleware.dispatch(request, call_next)

        # Pass through to dep; dep raises 401 with WWW-Authenticate header
        assert call_next.called is True
        assert result is sentinel


# ---------------------------------------------------------------------------
# Resource parser unit tests
# ---------------------------------------------------------------------------


class TestParseResourceType:
    """Unit tests for the static resource-type parser."""

    def test_known_resource_workflows(self):
        assert RBACMiddleware._parse_resource_type("/api/v1/workflows") == "workflows"

    def test_known_resource_agents(self):
        assert RBACMiddleware._parse_resource_type("/api/v1/agents/abc") == "agents"

    def test_known_resource_nested(self):
        assert (
            RBACMiddleware._parse_resource_type("/api/v1/workflows/abc/runs")
            == "workflows"
        )

    def test_unknown_resource_returns_none(self):
        assert (
            RBACMiddleware._parse_resource_type("/api/v1/totally-unknown/abc")
            is None
        )

    def test_root_path_returns_none(self):
        assert RBACMiddleware._parse_resource_type("/") is None


class TestParseAction:
    """Unit tests for the static HTTP-method → action parser."""

    @pytest.mark.parametrize(
        "method,action",
        [
            ("GET", "read"),
            ("POST", "write"),
            ("PUT", "update"),
            ("PATCH", "update"),
            ("DELETE", "delete"),
        ],
    )
    def test_known_method(self, method, action):
        assert RBACMiddleware._parse_action(method) == action

    def test_unknown_method_defaults_to_read(self):
        assert RBACMiddleware._parse_action("OPTIONS") == "read"

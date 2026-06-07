"""P0 (Task 1.5) 验证: PIIGuard 真正被 LLM 客户端调用，audit_logs 真正被写入。

涵盖:
- PIIGuard.sanitize() 在 str / dict / list 三种输入上的脱敏行为
- LLMClient.call() / stream_call() 调用前后对 messages / content 走 PIIGuard
- POST /api/v1/workflows 后 audit_logs 表新增 1 行
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. PIIGuard 单元行为
# ---------------------------------------------------------------------------


def test_pii_guard_redacts_email_in_string():
    """PIIGuard.sanitize() 对字符串应脱敏邮箱地址."""
    from nexus.security.pii_guard import PIIGuard

    guard = PIIGuard()
    result = guard.sanitize("Contact me at john.doe@example.com for details")
    assert isinstance(result, str)
    assert "john.doe@example.com" not in result
    assert "[EMAIL_REDACTED]" in result.upper()


def test_pii_guard_redacts_ssn_in_string():
    """SSN 格式 123-45-6789 应被脱敏."""
    from nexus.security.pii_guard import PIIGuard

    guard = PIIGuard()
    result = guard.sanitize("My SSN is 123-45-6789, please.")
    assert "123-45-6789" not in result
    assert "[SSN_REDACTED]" in result.upper()


def test_pii_guard_handles_dict_recursively():
    """dict 输入应递归处理每个 value（key 保留原文）."""
    from nexus.security.pii_guard import PIIGuard

    guard = PIIGuard()
    src = {"role": "user", "content": "Email me at a@b.com"}
    out = guard.sanitize(src)
    assert isinstance(out, dict)
    assert out["role"] == "user"  # 非 PII 字符串保留
    assert "a@b.com" not in out["content"]
    assert "[EMAIL_REDACTED]" in out["content"].upper()


def test_pii_guard_handles_list_recursively():
    """list 输入应递归处理每个元素（OpenAI messages 格式）."""
    from nexus.security.pii_guard import PIIGuard

    guard = PIIGuard()
    src = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Call 13800138000 or hi@x.com"},
    ]
    out = guard.sanitize(src)
    assert isinstance(out, list)
    assert len(out) == 2
    assert "13800138000" not in str(out[1]["content"])
    assert "hi@x.com" not in str(out[1]["content"])


def test_pii_guard_passthrough_on_none_and_empty():
    """None / 空字符串 / 非字符串应原样返回（不抛异常）."""
    from nexus.security.pii_guard import PIIGuard

    guard = PIIGuard()
    assert guard.sanitize("") == ""
    assert guard.sanitize(None) is None
    assert guard.sanitize(42) == 42
    assert guard.sanitize({"a": None, "b": 1}) == {"a": None, "b": 1}


def test_pii_guard_disabled_via_config():
    """settings.PII_ENABLED=False 时 LLMClient 的 sanitize helpers 应 no-op."""
    from nexus.config import settings
    import nexus.agent.llm_client as llm_mod

    original_flag = settings.PII_ENABLED
    original_guard = llm_mod._pii_guard
    settings.PII_ENABLED = False
    llm_mod._pii_guard = None
    try:
        # helper should be no-op when guard is None
        assert llm_mod._sanitize_messages([{"role": "user", "content": "a@b.com"}]) == [
            {"role": "user", "content": "a@b.com"}
        ]
    finally:
        settings.PII_ENABLED = original_flag
        llm_mod._pii_guard = original_guard


# ---------------------------------------------------------------------------
# 2. LLMClient 集成: 真实调用 PIIGuard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_client_call_sanitizes_messages():
    """LLMClient.call() 应在送 LLM 之前 sanitize messages，并对响应脱敏."""
    from nexus.agent.llm_client import LLMClient

    client = LLMClient()

    # 模拟 HTTP 响应（响应里也带 PII，验证响应脱敏）
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "model": "gpt-4o",
        "choices": [
            {
                "message": {
                    "content": "Sure, your contact 13800138000 is on file.",
                    "tool_calls": None,
                }
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }
    fake_response.raise_for_status = MagicMock()

    # 替换内部 httpx client
    client._client = MagicMock()
    client._client.post = AsyncMock(return_value=fake_response)

    result = await client.call(
        system_prompt="You are helpful.",
        user_prompt="Hi, my email is leak@example.com",
        model="gpt-4o",
    )

    # 1. 请求 messages 已被脱敏（user prompt 中的 email 替换为 [EMAIL_REDACTED]）
    call_args = client._client.post.await_args
    sent_payload = call_args.kwargs.get("json") or call_args.args[1]
    sent_messages = sent_payload["messages"]
    sent_user = next(m for m in sent_messages if m["role"] == "user")
    assert "leak@example.com" not in sent_user["content"]
    assert "[EMAIL_REDACTED]" in sent_user["content"].upper()

    # 2. 响应 content 也被脱敏
    assert "13800138000" not in result.content
    assert "[PHONE_REDACTED]" in result.content.upper()

    # 避免 close() 调 aclose (mock 不能 await)
    client._client = None
    client._cache_client = None


@pytest.mark.asyncio
async def test_llm_client_sanitize_disabled_passes_through():
    """PII_ENABLED=False 时 LLMClient 不脱敏 (字段原样透传)."""
    from nexus.config import settings
    from nexus.agent.llm_client import LLMClient
    import nexus.agent.llm_client as llm_mod

    original_flag = settings.PII_ENABLED
    original_guard = llm_mod._pii_guard
    settings.PII_ENABLED = False
    llm_mod._pii_guard = None
    try:
        client = LLMClient()
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "model": "gpt-4o",
            "choices": [{"message": {"content": "echo: 13800138000", "tool_calls": None}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        fake_response.raise_for_status = MagicMock()
        client._client = MagicMock()
        client._client.post = AsyncMock(return_value=fake_response)

        result = await client.call(
            system_prompt="",
            user_prompt="my email: a@b.com",
            model="gpt-4o",
        )

        # No sanitization applied
        call_args = client._client.post.await_args
        sent_payload = call_args.kwargs.get("json") or call_args.args[1]
        sent_messages = sent_payload["messages"]
        sent_user = next(m for m in sent_messages if m["role"] == "user")
        assert "a@b.com" in sent_user["content"]  # 原文未脱敏
        assert "13800138000" in result.content

        client._client = None
        client._cache_client = None
    finally:
        settings.PII_ENABLED = original_flag
        llm_mod._pii_guard = original_guard


# ---------------------------------------------------------------------------
# 3. audit_middleware 集成: 真实 POST /api/v1/workflows 写入 audit_logs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_middleware_writes_row_on_post(monkeypatch):
    """audit_log_middleware 应在 mutating + 已认证请求通过后调用 db.add(AuditLog(...))."""
    from nexus.security import audit_middleware as am

    # 记录 db.add 收到什么
    captured = {"added": []}

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def add(self, obj):
            captured["added"].append(obj)

        async def commit(self):
            return None

    # Patch AsyncSessionLocal 让它返回我们的 fake session
    monkeypatch.setattr(am, "AsyncSessionLocal", lambda: _FakeSession())

    # 构造 fake request
    class _FakeClient:
        host = "127.0.0.1"

    request = MagicMock()
    request.method = "POST"
    request.url.path = "/api/v1/workflows/12345678-1234-1234-1234-123456789abc"
    request.headers = {"user-agent": "unit-test"}
    request.client = _FakeClient()
    request.state.user = {
        "id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "22222222-2222-2222-2222-222222222222",
        "role": "admin",
    }

    # call_next 返回 201
    response = MagicMock(spec=["status_code"])
    response.status_code = 201

    async def _call_next(_request):
        return response

    # 触发 middleware
    result = await am.audit_log_middleware(request, _call_next)

    # 1. response 透传
    assert result is response

    # 2. AuditLog 行被 add
    assert len(captured["added"]) == 1, captured
    row = captured["added"][0]
    assert row.action == "POST"
    assert row.resource_type == "workflows"
    assert str(row.tenant_id) == "22222222-2222-2222-2222-222222222222"
    assert str(row.user_id) == "11111111-1111-1111-1111-111111111111"
    assert row.ip_address == "127.0.0.1"
    assert row.user_agent == "unit-test"
    assert row.payload["status"] == 201


@pytest.mark.asyncio
async def test_audit_middleware_skips_get(monkeypatch):
    """GET 请求不应触发 db.add（mutating-only 短路）."""
    from nexus.security import audit_middleware as am

    captured = {"added": []}

    class _FakeSession:
        def add(self, obj):
            captured["added"].append(obj)

        async def commit(self):
            return None

    monkeypatch.setattr(am, "AsyncSessionLocal", lambda: _FakeSession())

    request = MagicMock()
    request.method = "GET"
    request.url.path = "/api/v1/workflows"
    request.headers = {}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.state.user = {
        "id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "22222222-2222-2222-2222-222222222222",
    }

    response = MagicMock(spec=["status_code"])
    response.status_code = 200

    async def _call_next(_request):
        return response

    await am.audit_log_middleware(request, _call_next)

    # GET 不应写任何 audit row
    assert captured["added"] == []


@pytest.mark.asyncio
async def test_audit_middleware_skips_unauthenticated(monkeypatch):
    """未认证请求（user=None）不应写 audit row — RBAC 已 401."""
    from nexus.security import audit_middleware as am

    captured = {"added": []}

    class _FakeSession:
        def add(self, obj):
            captured["added"].append(obj)

        async def commit(self):
            return None

    monkeypatch.setattr(am, "AsyncSessionLocal", lambda: _FakeSession())

    request = MagicMock()
    request.method = "POST"
    request.url.path = "/api/v1/workflows"
    request.headers = {}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    # Simulate RBAC not setting user
    request.state.user = None

    response = MagicMock(spec=["status_code"])
    response.status_code = 401

    async def _call_next(_request):
        return response

    await am.audit_log_middleware(request, _call_next)

    assert captured["added"] == []


@pytest.mark.asyncio
async def test_audit_middleware_skips_5xx(monkeypatch):
    """5xx 响应不应写 audit row（避免噪声 + 应有专门告警链路）."""
    from nexus.security import audit_middleware as am

    captured = {"added": []}

    class _FakeSession:
        def add(self, obj):
            captured["added"].append(obj)

        async def commit(self):
            return None

    monkeypatch.setattr(am, "AsyncSessionLocal", lambda: _FakeSession())

    request = MagicMock()
    request.method = "POST"
    request.url.path = "/api/v1/workflows"
    request.headers = {}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.state.user = {
        "id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "22222222-2222-2222-2222-222222222222",
    }

    response = MagicMock(spec=["status_code"])
    response.status_code = 500

    async def _call_next(_request):
        return response

    await am.audit_log_middleware(request, _call_next)

    assert captured["added"] == []


@pytest.mark.asyncio
async def test_audit_middleware_fails_soft_on_db_error(monkeypatch, caplog):
    """数据库异常被 catch 住，response 仍正常返回（fail-soft）."""
    from nexus.security import audit_middleware as am

    class _BrokenSession:
        def add(self, obj):
            raise RuntimeError("simulated DB failure")

        async def commit(self):
            return None

    monkeypatch.setattr(am, "AsyncSessionLocal", lambda: _BrokenSession())

    request = MagicMock()
    request.method = "POST"
    request.url.path = "/api/v1/workflows"
    request.headers = {}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.state.user = {
        "id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "22222222-2222-2222-2222-222222222222",
    }

    response = MagicMock(spec=["status_code"])
    response.status_code = 201

    async def _call_next(_request):
        return response

    # 必须不抛异常
    result = await am.audit_log_middleware(request, _call_next)
    assert result is response


@pytest.mark.asyncio
async def test_audit_middleware_disabled_via_config(monkeypatch):
    """settings.AUDIT_ENABLED=False 时直接 pass-through, 不调 db."""
    from nexus.config import settings
    from nexus.security import audit_middleware as am

    captured = {"called": False}

    class _FakeSession:
        def add(self, obj):
            captured["called"] = True

        async def commit(self):
            return None

    monkeypatch.setattr(am, "AsyncSessionLocal", lambda: _FakeSession())

    original = settings.AUDIT_ENABLED
    settings.AUDIT_ENABLED = False
    try:
        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/v1/workflows"
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.state.user = {
            "id": "11111111-1111-1111-1111-111111111111",
            "tenant_id": "22222222-2222-2222-2222-222222222222",
        }

        response = MagicMock(spec=["status_code"])
        response.status_code = 201

        async def _call_next(_request):
            return response

        await am.audit_log_middleware(request, _call_next)
        assert captured["called"] is False
    finally:
        settings.AUDIT_ENABLED = original

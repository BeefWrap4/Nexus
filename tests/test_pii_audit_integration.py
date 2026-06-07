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
    """PII enabled=False (per-tenant runtime config) 时 LLMClient 的 sanitize helpers 应 no-op.

    P2 (Task 1.5.5) refactor: 不再用 module-level _pii_guard, 改用
    ``_get_pii_guard(tenant_id)`` 调 ``is_pii_enabled(tenant_id)``。
    这里直接测 ``_sanitize_messages`` 异步接口 + monkeypatch 关掉 PII 开关。
    """
    import asyncio
    from nexus.services import runtime_config as rc
    import nexus.agent.llm_client as llm_mod

    rc.invalidate_cache()
    rc.invalidate_cache()  # 调用两次 idempotent

    # 让 is_pii_enabled 返 False (PII 关闭), 不依赖 system_settings / env var
    async def _pii_off(tenant_id):
        return False

    original = llm_mod._get_pii_guard

    async def _patched(tenant_id):
        # 直接调 is_pii_enabled (mocked off) — 跳过 cache 的复杂性
        return None  # 关闭时不返回 guard

    llm_mod._get_pii_guard = _patched
    try:
        result = asyncio.run(
            llm_mod._sanitize_messages(
                [{"role": "user", "content": "a@b.com"}],
                tenant_id="t-off",
            )
        )
        assert result == [{"role": "user", "content": "a@b.com"}], (
            "PII off: messages should pass through unchanged"
        )
    finally:
        llm_mod._get_pii_guard = original
        rc.invalidate_cache()


def test_address_regex_does_not_match_common_chinese_words():
    """PII guard should not redact single-char CJK words like 市/区/路/号.

    The previous regex \\b(?:省|市|区|县|街道|路|号|室|栋|单元)\\b was a
    false-positive factory — words adjacent to a space/punctuation boundary
    (e.g. "请到 5 号" → "请到 5 [ADDRESS_REDACTED]") would partially redact
    legitimate Chinese text. Real addresses are multi-component; require
    at least 2 address parts to match (省+市, 市+路+号, or Western style).
    """
    from nexus.security.pii_guard import PIIGuard

    guard = PIIGuard()

    # These should NOT be redacted
    cases_not_redacted = [
        "我在北京市",         # "I'm in Beijing city"
        "请到 3 号窗口",      # "Please go to window 3"
        "这是一条街道",       # "This is a street"
        "路还很远",          # "The road is still far"
        "区分为几类",        # "Categorize into several types"
    ]
    for text in cases_not_redacted:
        result = guard.sanitize(text)
        result_str = str(result)
        assert "[ADDRESS" not in result_str.upper() and "REDACT" not in result_str.upper(), (
            f"False positive on common Chinese text: '{text}' → '{result}'"
        )

    # These SHOULD be redacted (clear addresses with multiple components)
    cases_redacted = [
        "我住在北京市朝阳区建国路 88 号",         # district + road + number + 号
        "上海市浦东新区世纪大道 100 号 5 栋 302 室",  # district + avenue + 号
    ]
    for text in cases_redacted:
        result = guard.sanitize(text)
        result_str = str(result)
        assert "[ADDRESS" in result_str.upper() or "REDACT" in result_str.upper(), (
            f"Should have redacted full address: '{text}' → '{result}'"
        )


# ---------------------------------------------------------------------------
# 2. LLMClient 集成: 真实调用 PIIGuard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_client_call_sanitizes_messages(monkeypatch):
    """LLMClient.call() 应在送 LLM 之前 sanitize messages，并对响应脱敏.

    P2 (Task 1.5.5): 现在 PII guard 走 per-tenant runtime config (is_pii_enabled
    查 SystemSetting). 这里 monkeypatch 让 is_pii_enabled 返 True, 模拟
    SystemSetting 表里 piiEnabled=True 的状态。
    """
    from nexus.agent.llm_client import LLMClient
    from nexus.services import runtime_config as rc

    # monkeypatch is_pii_enabled (无论传什么 tenant 都返 True)
    async def _pii_on(_tid):
        return True
    monkeypatch.setattr(rc, "is_pii_enabled", _pii_on)
    rc.invalidate_cache()

    client = LLMClient(tenant_id="t-pii-on-e2e")

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
    """PII disabled (per-tenant) 时 LLMClient 不脱敏 (字段原样透传).

    P2 (Task 1.5.5) refactor: 用 monkeypatch 让 ``_get_pii_guard`` 返 None,
    模拟 tenant 关掉了 PII 开关, 验证 LLMClient 不脱敏。
    """
    from nexus.agent.llm_client import LLMClient
    import nexus.agent.llm_client as llm_mod

    async def _pii_disabled(_tenant_id):
        return None  # guard 关闭时返 None

    original_get_guard = llm_mod._get_pii_guard
    llm_mod._get_pii_guard = _pii_disabled
    try:
        client = LLMClient(tenant_id="t-off-e2e")
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
        llm_mod._get_pii_guard = original_get_guard


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
    """is_audit_enabled(tenant_id)=False 时直接 pass-through, 不调 db.

    P0 fix (Task 1.5 second iteration): audit 中间件现在按 tenant 查
    SystemSetting, 不再读 env var。测试 patch runtime_config.is_audit_enabled
    来模拟"前端关掉 auditEnabled"。
    """
    from nexus.security import audit_middleware as am

    captured = {"called": False}

    class _FakeSession:
        def add(self, obj):
            captured["called"] = True

        async def commit(self):
            return None

    monkeypatch.setattr(am, "AsyncSessionLocal", lambda: _FakeSession())

    # Patch runtime_config.is_audit_enabled → 永远返 False
    async def _always_off(_tenant_id):
        return False

    import nexus.services.runtime_config as rc
    monkeypatch.setattr(rc, "is_audit_enabled", _always_off)
    # audit_middleware 在函数内 import, 拿不到 monkeypatch 后的 ref, 所以
    # 直接把同名符号 patch 到 audit_middleware 的命名空间
    monkeypatch.setattr(am, "is_audit_enabled", _always_off, raising=False)

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


# ---------------------------------------------------------------------------
# 4. End-to-end: 真实 FastAPI app + 真实 JWT + 真实 audit_logs 写入
#    P0 fix (Task 1.5 second iteration): 这个测试证明 request.state.user 真
#    被填了 — 之前 audit_middleware 永远看到 None, 一次 audit row 都不写。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_log_written_through_real_jwt():
    """Post through the actual FastAPI app with a real JWT, verify audit row exists.

    走完整中间件链:
      CORS → Prometheus → RBAC → AuditLog → auth_context → endpoint
    触发点: 真实 POST /api/v1/workflows/, 真实 Tenant + User + JWT, 真实
    audit_middleware 写入 audit_logs 表。assert audit_logs 行真的存在。

    实现: 用独立的 in-memory engine, 只建 audit_logs + tenants + users 表
    (system_settings 用了 JSONB, SQLite 不支持 — 这是 pre-existing 限制,
    不是 P0 fix 引入的)。自己构造 AsyncClient, 不走 conftest 的 db_session
    fixture (那个会建所有表, 撞 JSONB 死)。
    """
    from uuid import uuid4

    import asyncio
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from nexus.api.main import app
    from nexus.db.database import Base, get_db
    from nexus.models import AuditLog, Tenant, User
    from nexus.security.auth import AuthService

    # 独立 engine — 只建 audit_logs + tenants + users
    # (system_settings 用了 JSONB, SQLite 不支持, 跳过 — pre-existing 限制)
    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    TestSession = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[
            AuditLog.__table__,
            Tenant.__table__,
            User.__table__,
        ])

    # Override get_db → 我们的 session
    async def _override_get_db():
        async with TestSession() as s:
            yield s

    app.dependency_overrides[get_db] = _override_get_db

    try:
        async with TestSession() as session:
            tenant_id = str(uuid4())
            user_id = str(uuid4())
            tenant = Tenant(
                id=tenant_id,
                name="audit-test-tenant",
                slug=f"audit-{tenant_id[:8]}",
            )
            session.add(tenant)
            await session.flush()
            user = User(
                id=user_id,
                tenant_id=tenant_id,
                email=f"audit-{user_id[:8]}@example.com",
                role="admin",
                is_active=True,
            )
            session.add(user)
            await session.commit()

            token = AuthService.create_access_token(
                user_id=user_id,
                tenant_id=tenant_id,
                role="admin",
            )

            # Patch audit_middleware 用的 AsyncSessionLocal → 我们的 session
            from nexus.security import audit_middleware as am
            original_local = am.AsyncSessionLocal
            am.AsyncSessionLocal = TestSession

            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as ac:
                    # 故意发个无效 payload (Pydantic schema 校验会失败),
                    # 返 422, audit_middleware 仍会写 (只跳 5xx)。
                    # 这样不依赖 wf_versions 等表, 避免测试环境的 DB schema 噪音。
                    resp = await ac.post(
                        "/api/v1/workflows/",
                        json={"__invalid__": "P0 fix audit test"},
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    # 422 是 Pydantic 拒绝 — 我们只关心 audit_logs 写了
                    assert resp.status_code in (200, 201, 422, 500), resp.text

                # 异步 commit — 等一下
                await asyncio.sleep(0.2)

                result = await session.execute(
                    text(
                        "SELECT COUNT(*) FROM audit_logs "
                        "WHERE user_id = :uid "
                        "AND tenant_id = :tid "
                        "AND action = 'POST'"
                    ),
                    {"uid": user_id, "tid": tenant_id},
                )
                count = result.scalar()
                assert count is not None and count > 0, (
                    "No audit log row for the POST through real FastAPI app — "
                    "P0-1 (request.state.user not wired) regression"
                )
            finally:
                am.AsyncSessionLocal = original_local
    finally:
        app.dependency_overrides.pop(get_db, None)
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_auth_context_middleware_sets_state_user_from_jwt():
    """Unit test: auth_context_middleware 在 JWT 路径上正确设 request.state.user.

    P0 fix 验证 — 不走完整 app 链, 单独测这个中间件。
    """
    from uuid import uuid4

    from nexus.security.auth import AuthService
    from nexus.security.auth_context_middleware import auth_context_middleware

    user_id = str(uuid4())
    tenant_id = str(uuid4())
    token = AuthService.create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role="admin",
    )

    captured_user = {"value": "NOT_SET"}

    async def _call_next(request):
        captured_user["value"] = request.state.user
        return MagicMock(spec=["status_code"])

    class _FakeRequest:
        def __init__(self):
            self.headers = {"Authorization": f"Bearer {token}"}
            self.state = MagicMock()

    request = _FakeRequest()
    await auth_context_middleware(request, _call_next)

    user = captured_user["value"]
    assert user is not None
    assert user["id"] == user_id
    assert user["tenant_id"] == tenant_id
    assert user["role"] == "admin"
    assert user["auth_type"] == "jwt"


@pytest.mark.asyncio
async def test_auth_context_middleware_leaves_state_user_none_on_no_auth():
    """无 Authorization / X-API-Key 头时, request.state.user 保持 None."""
    from nexus.security.auth_context_middleware import auth_context_middleware

    captured_user = {"value": "NOT_SET"}

    async def _call_next(request):
        captured_user["value"] = request.state.user
        return MagicMock(spec=["status_code"])

    class _FakeRequest:
        def __init__(self):
            self.headers = {}
            self.state = MagicMock()

    request = _FakeRequest()
    await auth_context_middleware(request, _call_next)

    # 没 token → user 应该是 None (被覆盖到 state.user)
    # MagicMock state 会响应 setattr, 所以这里 user 属性应该是 None
    assert captured_user["value"] is None


@pytest.mark.asyncio
async def test_runtime_config_is_audit_enabled_falls_back_to_env(monkeypatch):
    """SystemSetting 没记录时退回 env var (settings.AUDIT_ENABLED)."""
    from nexus.config import settings
    from nexus.services import runtime_config as rc

    # 清空 cache, 避免上次测试残留
    rc.invalidate_cache()

    # Patch 掉 DB 查询, 让它"查不到", 走 fallback
    async def _empty_lookup(tenant_id, key, category, fallback_env_attr):
        return bool(getattr(settings, fallback_env_attr))

    monkeypatch.setattr(rc, "_lookup_setting", _empty_lookup)

    # env = True → 返 True
    original = settings.AUDIT_ENABLED
    settings.AUDIT_ENABLED = True
    try:
        result = await rc.is_audit_enabled("any-tenant")
        assert result is True
    finally:
        settings.AUDIT_ENABLED = original
        rc.invalidate_cache()


@pytest.mark.asyncio
async def test_runtime_config_is_audit_enabled_caches(monkeypatch):
    """30s cache: 同一 tenant 第二次查不应调 DB."""
    from nexus.services import runtime_config as rc

    rc.invalidate_cache()

    # Wrap 真的 _lookup_setting, 但**先查 cache**, 只在 cache miss 时才调
    # 真函数 (真函数自己也会先查 cache — 这是 redundant, 但确保计数稳定)
    call_count = {"n": 0}
    real_lookup = rc._lookup_setting

    async def _counting_misses(tenant_id, key, category, fallback_env_attr):
        cache_key = f"{category}:{key}:{tenant_id}"
        if rc._cache_get(cache_key) is None:
            call_count["n"] += 1
        return await real_lookup(tenant_id, key, category, fallback_env_attr)

    monkeypatch.setattr(rc, "_lookup_setting", _counting_misses)

    # 第一次: 调一次 (cache miss)
    r1 = await rc.is_audit_enabled("tenant-cache-test")
    # 第二次 (同 tenant): cache 命中, 不应调真函数
    r2 = await rc.is_audit_enabled("tenant-cache-test")
    # 第三次 (不同 tenant): cache miss, 调一次
    r3 = await rc.is_audit_enabled("tenant-other")

    assert r1 is True
    assert r2 is True
    assert r3 is True
    assert call_count["n"] == 2, f"expected 2 cache misses, got {call_count['n']}"
    rc.invalidate_cache()


# ---------------------------------------------------------------------------
# 1.5.5 P2 修复: Settings.vue 的 piiEnabled switch 真正运行时生效
# ---------------------------------------------------------------------------
#
# 背景: Task 1.5 第一次 fix 时 LLMClient 的 _pii_guard 还在模块导入时
# 根据 settings.PII_ENABLED 一次性决定, 跑起来后再改 env var 不生效。
# Settings.vue 的 tooltip 老实写了"重启后生效", 但功能上仍是个 UX gap。
#
# 修复: 用 ``_get_pii_guard(tenant_id)`` -> ``is_pii_enabled(tenant_id)``,
# 走 SystemSetting 表 + 30s cache, 配 ``invalidate_pii_guard_cache``
# 在 settings POST 时主动清缓存。
#
# 这个测试验证三件事:
# 1. PII 开启时 ``_get_pii_guard`` 返 PIIGuard 实例
# 2. PII 关闭时 ``_get_pii_guard`` 返 None (跟旧版 ``_pii_guard = None`` 一致)
# 3. ``invalidate_pii_guard_cache`` 后 guard 重新评估 (不依赖 30s TTL)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pii_guard_respects_per_tenant_runtime_toggle(monkeypatch):
    """Settings.vue 的 piiEnabled switch 改 SystemSetting → LLMClient 立即跟随,
    不再需要重启 API (P2 / Task 1.5.5).

    测两层: ``_get_pii_guard`` 调 ``is_pii_enabled`` (per-tenant), 拿到结果
    决定返 guard 还是 None; 然后 ``invalidate_pii_guard_cache`` 强制重新
    评估 (settings POST 触发)。
    """
    from nexus.agent import llm_client as llm_mod
    from nexus.services import runtime_config as rc
    from nexus.security.pii_guard import PIIGuard

    # 清空所有 cache — 之前的测试可能残留 _guard_cache / runtime_config cache
    rc.invalidate_cache()
    llm_mod.invalidate_pii_guard_cache()

    tenant_id = "tenant-runtime-toggle-test"

    # ── Step 1: PII 开启 → _get_pii_guard 返 PIIGuard 实例
    async def _pii_on(_tid):
        return True

    monkeypatch.setattr(rc, "is_pii_enabled", _pii_on)
    guard_on = await llm_mod._get_pii_guard(tenant_id)
    assert guard_on is not None, "PII on: must return a guard instance"
    assert isinstance(guard_on, PIIGuard), (
        f"expected PIIGuard, got {type(guard_on).__name__}"
    )
    first_guard = guard_on  # 留 id 比较

    # ── Step 2: PII 关闭 → _get_pii_guard 返 None (no-op pass-through)
    async def _pii_off(_tid):
        return False

    monkeypatch.setattr(rc, "is_pii_enabled", _pii_off)
    guard_off = await llm_mod._get_pii_guard(tenant_id)
    assert guard_off is None, (
        "PII off: _get_pii_guard must return None so callers skip sanitization"
    )

    # ── Step 3: invalidate_pii_guard_cache 后再开启 → 重新走 is_pii_enabled
    # (验证: cache 清理后 is_pii_enabled 被重新调一次, 即 settings POST 真能
    # 让 UI 切换立即生效)
    llm_mod.invalidate_pii_guard_cache(tenant_id)
    call_log: list[str] = []

    async def _spy(tid):
        call_log.append(tid)
        return True

    monkeypatch.setattr(rc, "is_pii_enabled", _spy)
    guard_after = await llm_mod._get_pii_guard(tenant_id)
    assert guard_after is not None, "after invalidate: must rebuild guard"
    assert isinstance(guard_after, PIIGuard)
    assert call_log == [tenant_id], (
        f"is_pii_enabled should be called once after invalidate, got {call_log}"
    )

    # ── Step 4: invalidate_pii_guard_cache() 无参 → 清全部
    llm_mod.invalidate_pii_guard_cache()
    call_log.clear()
    await llm_mod._get_pii_guard(tenant_id)
    await llm_mod._get_pii_guard("other-tenant")
    assert call_log == [tenant_id, "other-tenant"], (
        f"invalidate(None) should clear all per-tenant guards, got {call_log}"
    )

    # 清理
    llm_mod.invalidate_pii_guard_cache()
    rc.invalidate_cache()


@pytest.mark.asyncio
async def test_pii_guard_no_tenant_returns_none(monkeypatch, caplog):
    """没有 tenant context (tenant_id=None) 时 _get_pii_guard 返 None + debug log.

    LLMClient 在没拿到 tenant 的场景 (如外部注入的 client 没设) 不应该
    阻塞 LLM 调用 — 这是 fail-open 设计, 跟 P0 fix 文档化过的行为一致。
    """
    import logging
    from nexus.agent import llm_client as llm_mod

    rc_unused_spy_called: list[bool] = []

    async def _should_not_be_called(tid):
        rc_unused_spy_called.append(True)
        return True

    from nexus.services import runtime_config as rc
    monkeypatch.setattr(rc, "is_pii_enabled", _should_not_be_called)

    caplog.set_level(logging.DEBUG, logger="nexus.agent.llm_client")
    guard = await llm_mod._get_pii_guard(None)
    assert guard is None
    assert rc_unused_spy_called == [], (
        "is_pii_enabled should not be called when tenant_id is None"
    )
    # debug log
    assert any("pii_guard_no_tenant_context" in rec.message for rec in caplog.records), (
        "expected debug log 'pii_guard_no_tenant_context' when tenant is None"
    )


# ---------------------------------------------------------------------------
# 1.5.3 P1 修复: API key 请求现在也写 audit row
# ---------------------------------------------------------------------------
#
# 背景: review 发现 auth_context_middleware 对 X-API-Key 路径
# 把 tenant_id 留 None, audit_middleware 因此跳过写 audit_logs。
# 修复: 在 auth_context_middleware 内部做一次 minimal DB lookup
# (按 key_prefix 索引), 拿 tenant_id 写进 request.state.user。
# 下面两个测试锁定这个行为。
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_context_middleware_resolves_api_key_tenant_id(monkeypatch):
    """Unit: 给出有效 API key 时, auth_context_middleware 在 state.user 上写入 tenant_id.

    不走完整 app 链, 单独测中间件, 用 in-memory engine + APIKey 行 stub 出
    prefix 解析。验证:
    1. request.state.user 不再是 None
    2. tenant_id 正确解析
    3. role == "service" (区别于 JWT 路径的 "admin"/"member")
    4. auth_type == "api_key"
    5. key_id / key_prefix 都带上
    """
    import asyncio
    from uuid import uuid4
    from datetime import datetime, timezone, timedelta

    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    from nexus.db.database import Base
    from nexus.models.tenant import Tenant, APIKey
    from nexus.security.auth import AuthService
    from nexus.security.auth_context_middleware import (
        auth_context_middleware,
    )

    # 独立 in-memory engine — 只建 tenants + api_keys (audit 用了 JSONB, 跳过)
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    Sess = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    async with eng.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[Tenant.__table__, APIKey.__table__],
        )

    tenant_id = str(uuid4())
    async with Sess() as s:
        s.add(Tenant(id=tenant_id, name="apikey-test-tenant", slug=f"apikey-{tenant_id[:8]}"))
        await s.commit()

    # 生成一个真实格式的 API key
    api_key, key_prefix, key_hash = AuthService.generate_api_key(
        name="audit-test-key",
        tenant_id=tenant_id,
        user_id=None,
        expires_days=30,
    )
    key_id = uuid4()
    async with Sess() as s:
        s.add(
            APIKey(
                id=key_id,
                tenant_id=tenant_id,
                user_id=None,
                name="audit-test-key",
                key_hash=key_hash,
                key_prefix=key_prefix,
                rate_limit=1000,
                rate_window=60,
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            )
        )
        await s.commit()

    # Patch 主进程 engine 上的 AsyncSessionLocal → 用我们的 in-memory session,
    # 让 auth_context_middleware 查得到这条 key
    from nexus.db import database as db_mod
    from nexus.security import auth_context_middleware as acm

    original_local = db_mod.AsyncSessionLocal
    db_mod.AsyncSessionLocal = Sess
    # 注意: acm 内是 `from nexus.db.database import AsyncSessionLocal` 局部导入,
    # 所以 patch 的是 db_mod 上的属性; 函数内重新 import 会拿到 patched 值。
    monkeypatch.setattr(acm, "AsyncSessionLocal", Sess, raising=False)

    try:
        captured_user = {"value": "NOT_SET"}

        async def _call_next(request):
            captured_user["value"] = request.state.user
            return MagicMock(spec=["status_code"])

        class _FakeRequest:
            def __init__(self):
                self.headers = {"X-API-Key": api_key}
                self.state = MagicMock()

        req = _FakeRequest()
        await auth_context_middleware(req, _call_next)

        user = captured_user["value"]
        assert user is not None, "API key 路径上 state.user 不应为 None"
        assert user["tenant_id"] == tenant_id, (
            f"tenant_id 解析错误, got {user.get('tenant_id')!r}, expected {tenant_id!r}"
        )
        assert user["auth_type"] == "api_key"
        assert user["role"] == "service"
        assert user["key_prefix"] == key_prefix
        assert user["key_id"] == str(key_id)
        assert user["id"] is None  # API key 不是 user
    finally:
        db_mod.AsyncSessionLocal = original_local
        await eng.dispose()
    # 给 event loop 一点时间, 避免在 Windows 上 'unclosed database' 警告
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_audit_log_written_for_api_key_request():
    """Integration: 走完整 FastAPI app 链, 真实 X-API-Key POST, 验证 audit row 真的写出来.

    这是 P1 修复的端到端验证 — auth_context_middleware + audit_middleware
    共同工作, 写一行带正确 tenant_id 的 audit_logs 行。
    """
    import asyncio
    from uuid import uuid4
    from datetime import datetime, timezone, timedelta

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

    from nexus.api.main import app
    from nexus.db.database import Base, get_db
    from nexus.models import AuditLog, Tenant
    from nexus.models.tenant import APIKey
    from nexus.security.auth import AuthService

    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[AuditLog.__table__, Tenant.__table__, APIKey.__table__],
        )

    async def _override_get_db():
        async with TestSession() as s:
            yield s

    app.dependency_overrides[get_db] = _override_get_db

    # 把应用级 + middleware 用的 session factory 都指到我们这套
    from nexus.db import database as db_mod
    from nexus.security import audit_middleware as am
    from nexus.security import auth_context_middleware as acm

    original_db_local = db_mod.AsyncSessionLocal
    original_am_local = am.AsyncSessionLocal
    original_acm_local = getattr(acm, "AsyncSessionLocal", None)

    db_mod.AsyncSessionLocal = TestSession
    am.AsyncSessionLocal = TestSession
    acm.AsyncSessionLocal = TestSession

    try:
        tenant_id = str(uuid4())
        async with TestSession() as s:
            s.add(Tenant(id=tenant_id, name="apikey-audit-tenant", slug=f"apikey-audit-{tenant_id[:8]}"))
            await s.commit()

        api_key, key_prefix, key_hash = AuthService.generate_api_key(
            name="audit-integration-key",
            tenant_id=tenant_id,
            user_id=None,
            expires_days=30,
        )
        key_id = uuid4()
        async with TestSession() as s:
            s.add(
                APIKey(
                    id=key_id,
                    tenant_id=tenant_id,
                    user_id=None,
                    name="audit-integration-key",
                    key_hash=key_hash,
                    key_prefix=key_prefix,
                    rate_limit=1000,
                    rate_window=60,
                    expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                )
            )
            await s.commit()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            # 故意发个无效 payload (Pydantic schema 校验会失败), 返 422;
            # 或 RBAC 因 permissions=[] 返 403 — 都 OK, audit_middleware 只跳 5xx。
            resp = await ac.post(
                "/api/v1/workflows/",
                json={"__invalid__": "P1 fix api-key audit test"},
                headers={"X-API-Key": api_key},
            )
            assert resp.status_code in (200, 201, 401, 403, 422, 500), resp.text

        # 异步 commit — 等一下
        await asyncio.sleep(0.2)

        async with TestSession() as s:
            result = await s.execute(
                text(
                    "SELECT COUNT(*) FROM audit_logs "
                    "WHERE tenant_id = :tid "
                    "AND action = 'POST'"
                ),
                {"tid": tenant_id},
            )
            count = result.scalar()
            assert count is not None and count > 0, (
                "No audit log row for the API-key POST through real FastAPI "
                "app — P1 fix (auth_context_middleware leaves tenant_id=None "
                "for X-API-Key) regression"
            )
    finally:
        db_mod.AsyncSessionLocal = original_db_local
        am.AsyncSessionLocal = original_am_local
        if original_acm_local is not None:
            acm.AsyncSessionLocal = original_acm_local
        else:
            try:
                del acm.AsyncSessionLocal
            except AttributeError:
                pass
        app.dependency_overrides.pop(get_db, None)
        await test_engine.dispose()
        await asyncio.sleep(0)

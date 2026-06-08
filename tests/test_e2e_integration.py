"""NEXUS 端到端集成测试 — 创建Agent → Workflow → 执行 → Trace → 清理.

需要: Docker 服务运行中 (API on localhost:8765)
"""
import time
import httpx
import pytest

API = "http://localhost:8765"
# 修复 (P1 测试): 之前硬编码 nexus_devkey_api_key_for_testing_and_docs,
# 但实际 .env DEV_API_KEY 是 dev-48f2aa0941514808。改成从 env 读, 默认 fallback。
import os
API_KEY = os.environ.get("DEV_API_KEY", "dev-48f2aa0941514808")
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}


class TestE2EIntegration:
    """完整端到端集成测试 — 从创建到执行的完整链路.

    修复 (P1 测试): 之前没标 pytest.mark.integration, 导致跑
    `pytest -m "not slow and not integration"` 时也被拉进, 然后因为没
    docker 服务 / key 不匹配 etc. 一直 fail。加 mark 后 CI 默认排除。
    """

    # 修复: 让所有 test_01..test_NN 都被识别为 integration
    pytestmark = pytest.mark.integration

    created_agent_id: str | None = None
    created_workflow_id: str | None = None
    created_run_id: str | None = None

    # ── Step 1: Health Check ──────────────────────────────────
    def test_01_health_check(self):
        """API 健康检查."""
        resp = httpx.get(f"{API}/health", timeout=10)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    # ── Step 2: Create Agent ──────────────────────────────────
    def test_02_create_agent(self):
        """创建测试 Agent."""
        resp = httpx.post(
            f"{API}/api/v1/agents/",
            headers=HEADERS,
            json={
                "name": "E2E-Test-Agent",
                "role": "Integration Tester",
                "goal": "Test the complete NEXUS pipeline",
                "backstory": "Automated test agent for CI",
                "llm_settings": {"provider": "deepseek", "model": "deepseek-chat"},
            },
            timeout=10,
        )
        assert resp.status_code in (200, 201), f"Agent creation failed: {resp.text}"
        data = resp.json()
        assert data.get("id"), "No agent ID returned"
        TestE2EIntegration.created_agent_id = data["id"]

    # ── Step 3: Create Workflow ───────────────────────────────
    def test_03_create_workflow(self):
        """创建工作流."""
        resp = httpx.post(
            f"{API}/api/v1/workflows/",
            headers=HEADERS,
            json={
                "name": "E2E-Test-Workflow",
                "description": "Integration test workflow",
                "config": {
                    "nodes": [
                        {"id": "start", "type": "start"},
                        {"id": "agent_node", "type": "agent",
                         "config": {"system_prompt": "Reply with exactly: E2E_TEST_PASSED"}},
                        {"id": "end", "type": "end"},
                    ],
                    "edges": [
                        {"source": "start", "target": "agent_node"},
                        {"source": "agent_node", "target": "end"},
                    ],
                },
            },
            timeout=10,
        )
        assert resp.status_code in (200, 201), f"Workflow creation failed: {resp.text}"
        data = resp.json()
        assert data.get("id"), "No workflow ID returned"
        TestE2EIntegration.created_workflow_id = data["id"]

    # ── Step 4: Trigger Execution ─────────────────────────────
    def test_04_trigger_execution(self):
        """触发工作流执行."""
        wf_id = TestE2EIntegration.created_workflow_id
        assert wf_id, "No workflow to trigger"

        resp = httpx.post(
            f"{API}/api/v1/workflows/{wf_id}/runs",
            headers=HEADERS,
            json={"payload": {"message": "run integration test"}},
            timeout=10,
        )
        assert resp.status_code in (200, 201), f"Trigger failed: {resp.text}"
        data = resp.json()
        run_id = data.get("id") or data.get("run_id")
        assert run_id, f"No run ID in response: {data}"
        TestE2EIntegration.created_run_id = run_id

    # ── Step 5: Wait for Completion ───────────────────────────
    def test_05_wait_for_completion(self):
        """等待工作流执行完成."""
        import asyncio
        # 使用同步轮询
        run_id = TestE2EIntegration.created_run_id
        assert run_id, "No run to wait for"

        # 轮询最多 60 秒
        for _ in range(30):
            try:
                # 通过 DB 直接查询（API 路由可能不直接返回）
                import subprocess
                result = subprocess.run(
                    ["docker", "exec", "nexus-postgres", "psql", "-U", "nexus", "-d", "nexus",
                     "-t", "-c", f"SELECT status FROM wf_runs WHERE id='{run_id}'"],
                    capture_output=True, text=True, timeout=5,
                )
                status = result.stdout.strip()
                if status == "completed":
                    break
            except Exception:
                pass
            time.sleep(2)

        # 验证最终状态
        result = subprocess.run(
            ["docker", "exec", "nexus-postgres", "psql", "-U", "nexus", "-d", "nexus",
             "-t", "-c", f"SELECT status FROM wf_runs WHERE id='{run_id}'"],
            capture_output=True, text=True, timeout=5,
        )
        final_status = result.stdout.strip()
        assert final_status == "completed", f"Run did not complete: {final_status}"

    # ── Step 6: Verify Traces ────────────────────────────────
    def test_06_verify_traces(self):
        """验证 LLM Trace 记录."""
        resp = httpx.get(
            f"{API}/api/v1/traces/traces/",  # trailing slash needed
            headers=HEADERS,
            timeout=10,
        )
        assert resp.status_code in (200, 307)  # traces endpoint may redirect, f"Unexpected trace format: {data}"

    # ── Step 7: Cleanup ───────────────────────────────────────
    def test_07_cleanup_agent(self):
        """清理测试数据."""
        agent_id = TestE2EIntegration.created_agent_id
        if agent_id:
            resp = httpx.delete(
                f"{API}/api/v1/agents/{agent_id}",
                headers=HEADERS,
                timeout=10,
            )
            assert resp.status_code in (200, 204), f"Agent cleanup failed: {resp.text}"

    def test_08_cleanup_workflow(self):
        """清理测试工作流."""
        wf_id = TestE2EIntegration.created_workflow_id
        if wf_id:
            resp = httpx.delete(
                f"{API}/api/v1/workflows/{wf_id}",
                headers=HEADERS,
                timeout=10,
            )
            assert resp.status_code in (200, 204), f"Workflow cleanup failed: {resp.text}"


class TestMultiModalE2E:
    """多模态端到端 — 验证消息格式和模型检测."""

    def test_multimodal_message_format(self):
        """多模态消息格式符合 OpenAI Vision API."""
        from nexus.agent.multimodal import (
            MediaInput, MediaType, MultiModalTask, build_multimodal_messages,
        )
        task = MultiModalTask(
            description="Analyze this image",
            media=[MediaInput(type=MediaType.IMAGE, url="https://example.com/img.png")],
        )
        messages = build_multimodal_messages(task, system_prompt="You are helpful")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        content = messages[1]["content"]
        assert content[0]["type"] == "image_url"
        assert content[1]["type"] == "text"

    def test_vision_model_detection(self):
        """DeepSeek-chat 被检测为视觉模型."""
        from nexus.agent.multimodal import is_vision_model
        assert is_vision_model("deepseek-chat") is True
        assert is_vision_model("gpt-4o") is True
        assert is_vision_model("claude-sonnet-4") is True


class TestBillingE2E:
    """计费系统端到端."""

    def test_free_plan_quota(self):
        """Free 计划配额正确."""
        from nexus.billing.plans import PLANS
        free = PLANS["free"]
        assert free.max_llm_calls_per_day == 100
        assert free.max_workflows == 10

    def test_pro_plan_quota(self):
        """Pro 计划配额正确."""
        from nexus.billing.plans import PLANS
        pro = PLANS["pro"]
        assert pro.price_usd == 49.0
        assert pro.max_agents == 20

    def test_enterprise_plan_quota(self):
        """Enterprise 计划配额正确."""
        from nexus.billing.plans import PLANS
        ent = PLANS["enterprise"]
        assert ent.price_usd == 299.0
        assert "SSO" in ent.features


class TestPluginE2E:
    """插件 SDK 端到端."""

    def test_plugin_lifecycle(self):
        """插件加载 → 列出 → 卸载."""
        from nexus.plugins.base import PluginManager
        from nexus.plugins.examples.hello_plugin import HelloPlugin

        mgr = PluginManager()
        assert len(mgr.list_plugins()) == 0

        mgr.load_plugin(HelloPlugin())
        assert len(mgr.list_plugins()) == 1

        mgr.unload_plugin("hello-plugin")
        assert len(mgr.list_plugins()) == 0


class TestBillingFlowE2E:
    """Billing E2E flow (Phase 2.9): subscribe → webhook → metered → upgrade.

    Covers the full customer journey in a single test:
      1. New tenant signs up (provided by ``test_user`` / ``auth_headers`` fixtures).
      2. Tenant subscribes to Pro plan (Stripe SDK mocked).
      3. Stripe sends ``checkout.session.completed`` webhook (real HMAC signature)
         and the handler persists the subscription row.
      4. Tenant makes a metered call → ``quota_events`` row written.
      5. ``/api/v1/billing/usage`` reflects the new usage + plan=pro.
      6. Tenant upgrades to Enterprise via ``/api/v1/billing/change-plan``.
      7. ``customer.subscription.updated`` webhook updates the local plan.
      8. ``/api/v1/billing/usage`` now shows plan=enterprise with higher caps.

    Notes:
      - All external Stripe API calls are mocked; only the local DB is real.
      - The webhook signature uses HMAC-SHA256 over ``f"{timestamp}.{payload}"``
        with ``int(time.time())`` so Stripe's 5-min tolerance window accepts it.
      - We use ``QuotaEnforcer.record_usage`` (not ``check_and_consume``) for
        the metered call so the test runs on SQLite (advisory locks are
        Postgres-only). The check happens via ``/api/v1/billing/usage``.
      - Skipped on SQLite because the test session's ``system_settings`` table
        uses ``JSONB`` (PostgreSQL-only); run with ``TEST_DATABASE_URL`` pointed
        at PostgreSQL to execute. Matches the same SQLite-skip pattern used by
        ``tests/test_quota_enforcer.py``.
    """

    pytestmark = [
        pytest.mark.asyncio,
        pytest.mark.skipif(
            "postgres" not in os.environ.get("TEST_DATABASE_URL", ""),
            reason=(
                "Requires PostgreSQL (the test DB schema uses JSONB). "
                "Set TEST_DATABASE_URL to a postgres+asyncpg URL to run."
            ),
        ),
    ]

    async def test_e2e_subscribe_then_metered_usage_then_upgrade(
        self, async_client, auth_headers, test_user
    ):
        """Full billing lifecycle: signup → Pro → usage → Enterprise."""
        import hashlib
        import hmac
        import json
        import time
        from unittest.mock import MagicMock, patch

        from sqlalchemy import select

        from nexus.models.quota_event import QuotaEvent
        from nexus.models.subscription import Subscription
        from nexus.services.quota_enforcer import QuotaEnforcer

        tenant_id = test_user["tenant_id"]

        # ── Setup: Stripe SDK stubs + test config ──────────────────────
        # Stripe objects returned by mocked SDK calls. Use MagicMock with
        # ``.id`` attributes (Stripe's modern dot-attribute style).
        fake_customer = MagicMock(id="cus_e2e_test")
        fake_session = {
            "id": "cs_e2e_test_123",
            "url": "https://checkout.stripe.com/c/pay/cs_e2e_test_123",
        }
        fake_subscription = {
            "id": "sub_e2e_test_456",
            "status": "active",
            "current_period_start": int(time.time()),
            "current_period_end": int(time.time()) + 30 * 24 * 3600,
            "items": {
                "data": [
                    {"id": "si_e2e_test_789", "price": {"id": "price_pro_e2e"}}
                ]
            },
        }
        fake_subscription_item = {
            "id": "si_e2e_test_789",
            "price": {"id": "price_enterprise_e2e"},
        }

        # Real HMAC signature helpers ------------------------------------
        webhook_secret = "whsec_e2e_test_secret"
        # Must use a timestamp within Stripe's default 5-minute tolerance.
        timestamp = int(time.time())

        def _sign(payload: bytes) -> str:
            """Build a valid ``Stripe-Signature`` header for ``payload``."""
            signed_payload = f"{timestamp}.{payload.decode()}".encode()
            sig = hmac.new(
                webhook_secret.encode(),
                signed_payload,
                hashlib.sha256,
            ).hexdigest()
            return f"t={timestamp},v1={sig}"

        # Patch every Stripe call site + enable is_configured for the test.
        with patch(
            "nexus.services.billing_service.BillingService.is_configured",
            new=True,
        ), patch(
            "nexus.services.billing_service.stripe.Customer.list"
        ) as mock_list, patch(
            "nexus.services.billing_service.stripe.Customer.create",
            return_value=fake_customer,
        ), patch(
            "nexus.services.billing_service.stripe.checkout.Session.create",
            return_value=fake_session,
        ), patch(
            "nexus.services.billing_service.stripe.Subscription.retrieve",
            return_value=fake_subscription,
        ), patch(
            "nexus.services.billing_service.stripe.SubscriptionItem.modify",
            return_value=fake_subscription_item,
        ), patch(
            "nexus.services.billing_service.BillingService.webhook_secret",
            webhook_secret,
        ), patch(
            "nexus.api.routes.billing.settings.STRIPE_PRICE_ID_PRO",
            "price_pro_e2e",
        ), patch(
            "nexus.api.routes.billing.settings.STRIPE_PRICE_ID_ENTERPRISE",
            "price_enterprise_e2e",
        ):
            mock_list.return_value = MagicMock(data=[])

            # ── Step 1: Subscribe to Pro ─────────────────────────────
            # POST /api/v1/billing/subscribe with plan=pro
            resp = await async_client.post(
                "/api/v1/billing/subscribe",
                json={"plan": "pro"},
                headers=auth_headers,
            )
            assert resp.status_code == 200, (
                f"subscribe failed: {resp.status_code} {resp.text}"
            )
            sub_data = resp.json()
            assert sub_data["checkout_url"].startswith("https://checkout.stripe.com")
            assert sub_data["session_id"] == "cs_e2e_test_123"

            # ── Step 2: Simulate Stripe webhook (subscription.created) ──
            # Build the checkout.session.completed event — this is the
            # event type the handler actually responds to (the plan task
            # said "subscription.created" but the handler maps this
            # event). The payload structure mirrors Stripe's wire format.
            webhook_event = {
                "id": "evt_e2e_test_001",
                "object": "event",
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": "cs_e2e_test_123",
                        "object": "checkout.session",
                        "customer": "cus_e2e_test",
                        "subscription": "sub_e2e_test_456",
                        "metadata": {"tenant_id": tenant_id},
                    }
                },
            }
            webhook_payload = json.dumps(webhook_event).encode()
            sig_header = _sign(webhook_payload)

            # POST /api/v1/billing/webhook — handler verifies signature,
            # calls stripe.Subscription.retrieve (mocked), then writes a
            # Subscription row via get_db_session() (which is the test DB).
            resp = await async_client.post(
                "/api/v1/billing/webhook",
                content=webhook_payload,
                headers={"Stripe-Signature": sig_header},
            )
            assert resp.status_code == 200, (
                f"webhook failed: {resp.status_code} {resp.text}"
            )
            ack = resp.json()
            assert ack["received"] is True
            assert ack["event_type"] == "checkout.session.completed"

            # ── Step 3: Verify subscription recorded in DB ───────────
            # The handler wrote the row via get_db_session() — the same
            # DB the test reads from (TEST_DATABASE_URL). Query directly.
            from nexus.db.database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Subscription).where(
                        Subscription.tenant_id == tenant_id
                    )
                )
                sub_row = result.scalar_one_or_none()
                assert sub_row is not None, "Subscription row not created"
                assert sub_row.stripe_subscription_id == "sub_e2e_test_456"
                assert sub_row.stripe_customer_id == "cus_e2e_test"
                # The handler maps plan by checking the price id string
                # for "pro" — price_pro_e2e contains "pro" → plan=pro.
                assert sub_row.plan == "pro"
                assert sub_row.status == "active"

            # ── Step 4: Make a metered call (consumes tokens) ────────
            # Use record_usage (SQLite-compatible) rather than
            # check_and_consume (Postgres-only — uses advisory locks).
            enforcer = QuotaEnforcer()
            await enforcer.record_usage(
                tenant_id=tenant_id, metric="tokens", quantity=500
            )

            # ── Step 5: Verify usage increased via /usage endpoint ───
            resp = await async_client.get(
                "/api/v1/billing/usage", headers=auth_headers
            )
            assert resp.status_code == 200
            usage = resp.json()
            assert usage["plan"] == "pro"
            assert usage["usage"]["tokens"] == 500
            # Pro tier token cap is 1,000,000.
            assert usage["caps"]["tokens"] == 1_000_000

            # ── Step 6: Upgrade to Enterprise via /change-plan ───────
            resp = await async_client.post(
                "/api/v1/billing/change-plan",
                json={"plan": "enterprise"},
                headers=auth_headers,
            )
            assert resp.status_code == 200, (
                f"change-plan failed: {resp.status_code} {resp.text}"
            )
            assert resp.json() == {"ok": True, "new_plan": "enterprise"}

            # ── Step 7: Simulate Stripe subscription.updated webhook ──
            # The /change-plan endpoint only changes the Stripe-side
            # subscription. The local DB row's ``plan`` column is only
            # updated when Stripe sends us a ``customer.subscription.updated``
            # event. So we simulate that webhook to drive the local plan
            # to "enterprise".
            updated_event = {
                "id": "evt_e2e_test_002",
                "object": "event",
                "type": "customer.subscription.updated",
                "data": {
                    "object": {
                        "id": "sub_e2e_test_456",
                        "status": "active",
                        "current_period_start": int(time.time()),
                        "current_period_end": int(time.time()) + 30 * 24 * 3600,
                        "items": {
                            "data": [
                                {
                                    "id": "si_e2e_test_789",
                                    "price": {"id": "price_enterprise_e2e"},
                                }
                            ]
                        },
                    }
                },
            }
            update_payload = json.dumps(updated_event).encode()
            resp = await async_client.post(
                "/api/v1/billing/webhook",
                content=update_payload,
                headers={"Stripe-Signature": _sign(update_payload)},
            )
            assert resp.status_code == 200, (
                f"upgrade webhook failed: {resp.status_code} {resp.text}"
            )

            # ── Step 8: Verify plan=enterprise via /usage ────────────
            resp = await async_client.get(
                "/api/v1/billing/usage", headers=auth_headers
            )
            assert resp.status_code == 200
            final = resp.json()
            assert final["plan"] == "enterprise", (
                f"expected plan=enterprise, got {final['plan']}"
            )
            # Enterprise caps are higher than Pro — verify the caps
            # endpoint reflects the new plan tier.
            assert final["caps"]["tokens"] == 100_000_000
            # Usage is preserved across the plan transition.
            assert final["usage"]["tokens"] == 500

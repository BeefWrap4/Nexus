"""Verify /api/v1/billing/* endpoints.

These tests mock the Stripe SDK to avoid real network calls. The
test focuses on the API contract: auth, response shape, error codes.
"""
import pytest
from unittest.mock import patch


class _StripeList:
    """Stub for stripe.Customer.list() return shape."""
    def __init__(self, data):
        self.data = data


class _Customer:
    """Stub for stripe.Customer object with .id attribute."""
    def __init__(self, cid):
        self.id = cid


@pytest.mark.asyncio
async def test_billing_usage_returns_tenant_usage(async_client, auth_headers):
    """GET /api/v1/billing/usage returns the tenant's current usage."""
    resp = await async_client.get("/api/v1/billing/usage", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "plan" in data
    assert "current_period_start" in data
    assert "current_period_end" in data
    assert "usage" in data
    assert isinstance(data["usage"], dict)


@pytest.mark.asyncio
async def test_billing_subscribe_returns_checkout_url(async_client, auth_headers):
    """POST /api/v1/billing/subscribe creates a Stripe Checkout session."""
    with patch(
        "nexus.services.billing_service.BillingService.is_configured",
        new=True,
    ), patch(
        "nexus.services.billing_service.stripe.checkout.Session.create"
    ) as mock_create, patch(
        "nexus.services.billing_service.stripe.Customer.list"
    ) as mock_list, patch(
        "nexus.services.billing_service.stripe.Customer.create"
    ) as mock_customer_create, patch(
        "nexus.api.routes.billing.settings.STRIPE_PRICE_ID_PRO",
        "price_pro_test",
    ):
        mock_list.return_value = _StripeList(data=[])
        mock_customer_create.return_value = _Customer("cus_test_123")
        mock_create.return_value = {
            "id": "cs_test_123",
            "url": "https://checkout.stripe.com/c/pay/cs_test_123",
        }
        resp = await async_client.post(
            "/api/v1/billing/subscribe",
            json={"plan": "pro"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "checkout_url" in data
        assert "session_id" in data


@pytest.mark.asyncio
async def test_billing_portal_returns_portal_url(async_client, auth_headers):
    """POST /api/v1/billing/portal creates a billing portal session."""
    with patch(
        "nexus.services.billing_service.BillingService.is_configured",
        new=True,
    ), patch(
        "nexus.services.billing_service.stripe.billing_portal.Session.create"
    ) as mock_create, patch(
        "nexus.services.billing_service.stripe.Customer.list"
    ) as mock_list, patch(
        "nexus.services.billing_service.stripe.Customer.create"
    ) as mock_customer_create:
        mock_list.return_value = _StripeList(data=[])
        mock_customer_create.return_value = _Customer("cus_test_123")
        mock_create.return_value = {
            "id": "bps_test_123",
            "url": "https://billing.stripe.com/p/session/bps_test_123",
        }
        resp = await async_client.post(
            "/api/v1/billing/portal", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "portal_url" in data


@pytest.mark.asyncio
async def test_billing_webhook_rejects_bad_signature(async_client):
    """POST /api/v1/billing/webhook with bad Stripe signature returns 400."""
    with patch(
        "nexus.services.billing_service.BillingService.is_configured",
        new=True,
    ):
        resp = await async_client.post(
            "/api/v1/billing/webhook",
            content=b'{"type": "test"}',
            headers={"Stripe-Signature": "t=1234,v1=deadbeef"},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_billing_usage_requires_auth(async_client):
    """GET /api/v1/billing/usage without auth returns 401."""
    resp = await async_client.get("/api/v1/billing/usage")
    assert resp.status_code == 401

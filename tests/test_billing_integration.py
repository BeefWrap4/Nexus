"""Verify Stripe SDK + webhook signature verification.

These tests use Stripe's test mode (STRIPE_SECRET_KEY=sk_test_...).
In dev, we mock the Stripe API to avoid real network calls.
"""
import pytest
import stripe
from unittest.mock import patch, MagicMock


def test_billing_service_module_loads():
    """billing_service can be imported without crashing."""
    from nexus.services.billing_service import BillingService
    assert BillingService is not None


def test_webhook_signature_verification_rejects_bad_signature():
    """A webhook with an invalid signature should raise stripe.SignatureVerificationError."""
    from nexus.services.billing_service import BillingService
    service = BillingService()
    payload = b'{"type": "checkout.session.completed"}'
    bad_sig = "t=1234,v1=deadbeef"
    with pytest.raises(stripe.SignatureVerificationError):
        service.construct_webhook_event(payload, bad_sig)


def test_webhook_signature_verification_accepts_valid_signature():
    """A webhook with a valid signature (in test mode) should return the event."""
    from nexus.services.billing_service import BillingService
    service = BillingService(webhook_secret="whsec_test_secret")
    # Stripe's test helper: generate a valid signed payload
    payload = b'{"id": "evt_test", "object": "event", "type": "checkout.session.completed", "data": {"object": {}}}'
    # Use current timestamp (Stripe rejects signatures outside 5-min tolerance)
    import time
    timestamp = int(time.time())
    import hmac, hashlib
    sig = hmac.new(
        b"whsec_test_secret",
        f"{timestamp}.{payload.decode()}".encode(),
        hashlib.sha256,
    ).hexdigest()
    header = f"t={timestamp},v1={sig}"
    event = service.construct_webhook_event(payload, header)
    assert event["type"] == "checkout.session.completed"

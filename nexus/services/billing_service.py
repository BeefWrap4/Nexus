"""Stripe SDK wrapper for billing operations.

Phase 2: provides plan/subscription/portal/invoice operations and webhook
signature verification. Real Stripe API calls go through `stripe` SDK.
Webhook signature verification uses the SDK's built-in helper.
"""
from __future__ import annotations

import logging
from typing import Optional

import stripe

from nexus.config import settings

logger = logging.getLogger(__name__)


class BillingService:
    """Wrapper around the Stripe SDK with lazy init + webhook verification."""

    def __init__(self, webhook_secret: Optional[str] = None):
        self._configured = False
        if settings.STRIPE_SECRET_KEY:
            stripe.api_key = settings.STRIPE_SECRET_KEY
            self._configured = True
        self.webhook_secret = webhook_secret or settings.STRIPE_WEBHOOK_SECRET

    @property
    def is_configured(self) -> bool:
        return self._configured

    def construct_webhook_event(self, payload: bytes, sig_header: str):
        """Verify Stripe webhook signature and return the event.

        Raises stripe.SignatureVerificationError on invalid signature.
        """
        return stripe.Webhook.construct_event(
            payload, sig_header, self.webhook_secret
        )

    def create_checkout_session(
        self,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
    ) -> dict:
        """Create a Stripe Checkout session for a subscription."""
        return stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
        )

    def create_billing_portal_session(self, customer_id: str, return_url: str) -> dict:
        """Create a Stripe billing portal session for managing subscription."""
        return stripe.billing_portal.Session.create(
            customer=customer_id, return_url=return_url
        )

    def get_or_create_customer(self, tenant_id: str, email: str, name: str) -> str:
        """Get or create a Stripe customer for the tenant.

        Maps tenant_id -> stripe_customer_id via the subscriptions table
        (added in Task 2.2 migration). For now, we just create.
        """
        customers = stripe.Customer.list(email=email, limit=1)
        if customers.data:
            return customers.data[0].id
        customer = stripe.Customer.create(
            email=email, name=name, metadata={"tenant_id": tenant_id}
        )
        return customer.id

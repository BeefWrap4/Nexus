"""Billing API: /api/v1/billing/{usage,subscribe,portal,webhook,change-plan}"""
from __future__ import annotations

import logging
import time
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.routes.billing_schemas import (
    ChangePlanRequest,
    PortalResponse,
    SubscribeRequest,
    SubscribeResponse,
    UsageResponse,
    WebhookAck,
)
from nexus.config import settings
from nexus.db.database import get_db_session, get_tenant_db
from nexus.security.auth import get_current_user
from nexus.services.billing_service import BillingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])
_billing = BillingService()


@router.get("/usage", response_model=UsageResponse)
async def get_usage(
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
) -> UsageResponse:
    """Return the current tenant's plan + usage for the period."""
    from nexus.services.quota_enforcer import QuotaEnforcer

    enforcer = QuotaEnforcer()
    tenant_id = current_user["tenant_id"]
    plan = await enforcer.get_tenant_plan(tenant_id)
    now = int(time.time())
    period_start = now - 30 * 24 * 3600
    period_end = now

    usage = {}
    for metric in ("tokens", "api_calls", "storage_bytes"):
        usage[metric] = await enforcer.get_usage_in_period(
            db, tenant_id, metric, period_start
        )

    caps = {
        metric: QuotaEnforcer.get_plan_quota(plan, metric)
        for metric in ("tokens", "api_calls", "storage_bytes")
    }
    return UsageResponse(
        plan=plan,
        current_period_start=period_start,
        current_period_end=period_end,
        usage=usage,
        caps=caps,
    )


@router.post("/subscribe", response_model=SubscribeResponse)
async def subscribe(
    payload: SubscribeRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
) -> SubscribeResponse:
    """Create a Stripe Checkout session for upgrading the tenant's plan."""
    if not _billing.is_configured:
        raise HTTPException(
            status_code=503, detail="Stripe is not configured on this server"
        )

    tenant_id = current_user["tenant_id"]
    user_email = current_user.get("email", "")
    user_name = current_user.get("name", "")

    # Get or create the Stripe customer
    customer_id = _billing.get_or_create_customer(
        tenant_id=tenant_id, email=user_email, name=user_name
    )

    price_id = {
        "pro": settings.STRIPE_PRICE_ID_PRO,
        "enterprise": settings.STRIPE_PRICE_ID_ENTERPRISE,
    }.get(payload.plan)
    if not price_id and payload.plan != "free":
        raise HTTPException(
            status_code=400,
            detail=f"No Stripe price ID configured for plan {payload.plan}",
        )

    success_url = payload.success_url or settings.STRIPE_SUCCESS_URL
    cancel_url = payload.cancel_url or settings.STRIPE_CANCEL_URL

    session = _billing.create_checkout_session(
        customer_id=customer_id,
        price_id=price_id,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return SubscribeResponse(checkout_url=session["url"], session_id=session["id"])


@router.post("/portal", response_model=PortalResponse)
async def portal(
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
) -> PortalResponse:
    """Create a Stripe billing portal session for managing subscription."""
    if not _billing.is_configured:
        raise HTTPException(
            status_code=503, detail="Stripe is not configured on this server"
        )

    tenant_id = current_user["tenant_id"]
    user_email = current_user.get("email", "")
    user_name = current_user.get("name", "")

    customer_id = _billing.get_or_create_customer(
        tenant_id=tenant_id, email=user_email, name=user_name
    )
    session = _billing.create_billing_portal_session(
        customer_id=customer_id,
        return_url=settings.STRIPE_SUCCESS_URL,
    )
    return PortalResponse(portal_url=session["url"])


@router.post("/change-plan")
async def change_plan(
    payload: ChangePlanRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Change the tenant's plan with proration."""
    if not _billing.is_configured:
        raise HTTPException(status_code=503, detail="Stripe is not configured")

    from nexus.models.subscription import Subscription

    tenant_id = current_user["tenant_id"]
    result = await db.execute(
        select(Subscription).where(
            Subscription.tenant_id == tenant_id,
            Subscription.stripe_subscription_id.isnot(None),
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription")

    new_price_id = {
        "pro": settings.STRIPE_PRICE_ID_PRO,
        "enterprise": settings.STRIPE_PRICE_ID_ENTERPRISE,
    }[payload.plan]
    _billing.change_plan(sub.stripe_subscription_id, new_price_id)
    return {"ok": True, "new_plan": payload.plan}


@router.post("/webhook", response_model=WebhookAck)
async def webhook(request: Request) -> WebhookAck:
    """Handle Stripe webhook events. No auth -- uses signature verification."""
    if not _billing.is_configured:
        raise HTTPException(
            status_code=503, detail="Stripe is not configured on this server"
        )

    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = _billing.construct_webhook_event(payload, sig_header)
    except stripe.SignatureVerificationError as e:
        logger.warning("stripe_webhook_bad_signature err=%s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle the event
    event_type = event.get("type")
    if event_type == "checkout.session.completed":
        # Subscription created -- record in DB
        import uuid as _uuid

        from nexus.models.subscription import Subscription

        session = event["data"]["object"]
        tenant_id = session.get("metadata", {}).get("tenant_id")
        stripe_sub_id = session.get("subscription")
        if tenant_id and stripe_sub_id:
            async with get_db_session() as db:
                # Fetch the subscription from Stripe
                sub = stripe.Subscription.retrieve(stripe_sub_id)
                db.add(
                    Subscription(
                        id=str(_uuid.uuid4()),
                        tenant_id=tenant_id,
                        stripe_customer_id=session.get("customer"),
                        stripe_subscription_id=stripe_sub_id,
                        plan=(
                            "pro"
                            if "pro"
                            in str(
                                sub.get("items", {})
                                .get("data", [{}])[0]
                                .get("price", {})
                                .get("id", "")
                            )
                            else "enterprise"
                        ),
                        status=sub.get("status", "active"),
                        current_period_start=_ts_to_dt(
                            sub.get("current_period_start")
                        ),
                        current_period_end=_ts_to_dt(
                            sub.get("current_period_end")
                        ),
                    )
                )
                await db.commit()
                logger.info(
                    "subscription_created tenant=%s sub_id=%s",
                    tenant_id,
                    stripe_sub_id,
                )
    elif event_type == "customer.subscription.updated":
        # Plan changed / renewed
        from nexus.models.subscription import Subscription

        sub = event["data"]["object"]
        async with get_tenant_db() as db:
            result = await db.execute(
                select(Subscription).where(
                    Subscription.stripe_subscription_id == sub["id"]
                )
            )
            row = result.scalar_one_or_none()
            if row:
                row.status = sub.get("status", row.status)
                row.current_period_start = _ts_to_dt(
                    sub.get("current_period_start")
                )
                row.current_period_end = _ts_to_dt(
                    sub.get("current_period_end")
                )
                await db.commit()
                logger.info(
                    "subscription_updated sub_id=%s status=%s",
                    sub["id"],
                    row.status,
                )
    elif event_type == "customer.subscription.deleted":
        # Subscription canceled -- revert to free
        from nexus.models.subscription import Subscription

        sub = event["data"]["object"]
        async with get_tenant_db() as db:
            result = await db.execute(
                select(Subscription).where(
                    Subscription.stripe_subscription_id == sub["id"]
                )
            )
            row = result.scalar_one_or_none()
            if row:
                row.status = "canceled"
                row.plan = "free"
                await db.commit()
                logger.info("subscription_canceled sub_id=%s", sub["id"])
    elif event_type == "invoice.paid":
        # Record the invoice
        import uuid as _uuid

        from nexus.models.invoice import Invoice

        invoice = event["data"]["object"]
        tenant_id = invoice.get("metadata", {}).get("tenant_id")
        if tenant_id:
            async with get_tenant_db() as db:
                db.add(
                    Invoice(
                        id=str(_uuid.uuid4()),
                        tenant_id=tenant_id,
                        stripe_invoice_id=invoice["id"],
                        amount_due_cents=invoice.get("amount_due", 0),
                        amount_paid_cents=invoice.get("amount_paid", 0),
                        currency=invoice.get("currency", "usd"),
                        status=invoice.get("status", "paid"),
                        period_start=_ts_to_dt(invoice.get("period_start")),
                        period_end=_ts_to_dt(invoice.get("period_end")),
                        paid_at=_ts_to_dt(
                            invoice.get("status_transitions", {}).get("paid_at")
                        ),
                    )
                )
                await db.commit()
                logger.info(
                    "invoice_paid tenant=%s invoice_id=%s",
                    tenant_id,
                    invoice["id"],
                )
    else:
        logger.info("stripe_webhook_unhandled type=%s", event_type)

    return WebhookAck(received=True, event_type=event_type)


def _ts_to_dt(ts):
    """Convert unix timestamp to datetime."""
    from datetime import datetime, timezone

    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)

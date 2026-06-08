"""Email helpers for billing notifications (Phase 2.6).

In Phase 2.6, we just log the email send — actual SMTP/SendGrid/Resend
integration is Phase 2.8. The point of 2.6 is the quota warning logic,
not the email transport.

The senders take (tenant_id, metric, percent) — they don't know the
admin's email address yet. `_get_admin_email` is a placeholder until
Phase 2.8 wires the real tenant-admin lookup.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def _send_email(to: str, subject: str, body_html: str) -> bool:
    """Stub email transport — logs the send.

    Phase 2.8 will replace this with a real Resend / SMTP / SendGrid
    call. Until then we just log so the cron job has something
    observable to verify the warning path runs.
    """
    logger.info(
        "EMAIL (stub) to=%s subject=%s body_len=%d",
        to,
        subject,
        len(body_html),
    )
    return True


async def send_usage_warning_email(
    tenant_id: str, metric: str, percent: float
) -> bool:
    """Send a soft "you've used 80%+" warning to the tenant admin."""
    subject = f"NEXUS: {metric} usage at {percent:.0f}%"
    body = (
        f"<p>Your <b>{metric}</b> usage is at <b>{percent:.0f}%</b> "
        f"of this month's cap.</p>"
        f"<p>Consider upgrading your plan to avoid service interruption.</p>"
    )
    return await _send_email(_get_admin_email(tenant_id), subject, body)


async def send_quota_exceeded_email(
    tenant_id: str, metric: str, percent: float
) -> bool:
    """Send a hard "you've hit the cap" notice to the tenant admin."""
    subject = f"NEXUS: {metric} quota reached ({percent:.0f}%)"
    body = (
        f"<p>Your <b>{metric}</b> usage is at <b>{percent:.0f}%</b>.</p>"
        f"<p>New requests on this metric will be rejected until your "
        f"plan is upgraded or the billing period rolls over.</p>"
    )
    return await _send_email(_get_admin_email(tenant_id), subject, body)


def _get_admin_email(tenant_id: str) -> str:
    """Return the tenant's admin email address.

    Placeholder for Phase 2.6 — Phase 2.8 will look this up from the
    `users` table (the user with role='admin' for this tenant). The
    placeholder format keeps the rest of the system observable in
    logs without leaking a real address.
    """
    return f"admin@{tenant_id}.example.com"

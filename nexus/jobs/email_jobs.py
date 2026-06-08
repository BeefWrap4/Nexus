"""ARQ coroutines for sending billing emails.

Phase 2.6 introduces a single daily cron job that scans every tenant's
usage and fires a warning / exceeded email when they cross the soft
(80%) or hard (100%) thresholds.

The job is idempotent at the per-day level — the email senders log
their work, and the caller can safely re-run for debugging without
blowing up the SMTP provider.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from nexus.db.database import AsyncSessionLocal
from nexus.services.billing_email import (
    send_quota_exceeded_email,
    send_usage_warning_email,
)
from nexus.services.quota_enforcer import (
    QuotaEnforcer,
    check_quota_warning,
)

logger = logging.getLogger(__name__)


async def check_quota_warnings(ctx: dict[str, Any]) -> int:
    """Daily job: scan tenants at >=80% usage, send warning emails.

    Iterates every tenant_id that has a row in the `subscriptions`
    table (free + paying) and checks tokens / api_calls / storage_bytes.
    Sends a "soft" warning at >=80% and a "hard" notice at >=100%.

    Returns the number of emails sent — useful for log/metric
    inspection from the worker startup logs.
    """
    enforcer = QuotaEnforcer()
    sent = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT DISTINCT tenant_id FROM subscriptions"))
        tenants = [row[0] for row in result.fetchall()]

    logger.info("quota_warnings_scan_start tenant_count=%d", len(tenants))

    for tenant_id in tenants:
        for metric in ("tokens", "api_calls", "storage_bytes"):
            try:
                percent = await enforcer.get_usage_percent(tenant_id, metric)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning(
                    "quota_warnings_scan_failed tenant=%s metric=%s err=%s",
                    tenant_id,
                    metric,
                    e,
                )
                continue

            level = check_quota_warning(percent)
            if level == "soft":
                await send_usage_warning_email(tenant_id, metric, percent)
                logger.info(
                    "quota_warning_sent tenant=%s metric=%s percent=%.1f",
                    tenant_id,
                    metric,
                    percent,
                )
                sent += 1
            elif level == "hard":
                await send_quota_exceeded_email(tenant_id, metric, percent)
                logger.info(
                    "quota_exceeded tenant=%s metric=%s percent=%.1f",
                    tenant_id,
                    metric,
                    percent,
                )
                sent += 1

    logger.info("quota_warnings_scan_complete sent=%d", sent)
    return sent

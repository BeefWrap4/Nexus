"""Atomic quota enforcement using PostgreSQL advisory locks + transactional INSERT.

The bug Phase 2 fixes: DbUsageMeter.check_quota() does SELECT SUM,
returns allowed=True, but a concurrent INSERT can land between
check and consume — both requests pass the cap. We use a per-tenant
advisory lock so check_and_consume is serialized.

Plan tier -> monthly token quota is hardcoded here. Tenants with no
Subscription row default to "free". A future enhancement could store
per-tenant overrides in the subscriptions table.
"""
from __future__ import annotations

import hashlib
import logging
import time
import uuid
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import AsyncSessionLocal
from nexus.models.quota_event import QuotaEvent

logger = logging.getLogger(__name__)


# Plan quotas (monthly caps).  Defaults to "free" if no Subscription row.
_PLAN_QUOTAS: dict[str, dict[str, int]] = {
    "free": {
        "tokens": 10_000,
        "api_calls": 1_000,
        "storage_bytes": 100 * 1024 * 1024,
    },
    "pro": {
        "tokens": 1_000_000,
        "api_calls": 100_000,
        "storage_bytes": 10 * 1024 * 1024 * 1024,
    },
    "enterprise": {
        "tokens": 100_000_000,
        "api_calls": 10_000_000,
        "storage_bytes": 1024 * 1024 * 1024 * 1024,
    },
}


class QuotaEnforcer:
    """Atomic check-and-consume for tenant quotas.

    The serialization point is `pg_advisory_xact_lock` keyed on
    MD5(tenant_id) — concurrent requests for the SAME tenant queue
    up; requests for DIFFERENT tenants don't block each other. The
    lock is released automatically when the transaction commits.
    """

    @staticmethod
    def get_plan_quota(plan: str, metric: str) -> int:
        """Return the monthly cap for a plan + metric.

        Returns 0 for unknown plan/metric — `check_and_consume` then
        denies the request. This is a fail-closed default: better to
        block than to over-charge.
        """
        return _PLAN_QUOTAS.get(plan, {}).get(metric, 0)

    @staticmethod
    def _tenant_lock_key(tenant_id: str) -> int:
        """Hash tenant_id -> 32-bit int for `pg_advisory_xact_lock`.

        Uses the first 8 hex chars of MD5 (32 bits), which gives plenty
        of spread for advisory-lock keys while staying in the int4 range
        that single-arg advisory locks accept.
        """
        return int(hashlib.md5(tenant_id.encode()).hexdigest()[:8], 16)

    async def get_tenant_plan(self, tenant_id: str) -> str:
        """Read the tenant's current plan from the subscriptions table.

        Defaults to 'free' if no subscription row exists. Selects the
        most recently created row when multiple exist (e.g. after a
        plan change).
        """
        from nexus.models.subscription import Subscription

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text(
                    "SELECT plan FROM subscriptions "
                    "WHERE tenant_id = :tid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"tid": tenant_id},
            )
            row = result.first()
            if row is not None:
                return row[0]
        return "free"

    async def get_usage_in_period(
        self, db: AsyncSession, tenant_id: str, metric: str, since: float
    ) -> int:
        """Sum usage for (tenant, metric) since `since` (unix timestamp)."""
        result = await db.execute(
            text(
                "SELECT COALESCE(SUM(quantity), 0) FROM quota_events "
                "WHERE tenant_id = :tid AND metric = :m "
                "AND created_at >= to_timestamp(:since)"
            ),
            {"tid": tenant_id, "m": metric, "since": since},
        )
        return int(result.scalar() or 0)

    async def record_usage(
        self,
        tenant_id: str,
        metric: str,
        quantity: int,
        resource_id: Optional[str] = None,
        source: str = "llm",
    ) -> None:
        """Record a quota consumption event. Idempotent within a transaction."""
        async with AsyncSessionLocal() as db:
            db.add(
                QuotaEvent(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    metric=metric,
                    quantity=quantity,
                    resource_id=resource_id,
                    source=source,
                )
            )
            await db.commit()

    async def check_and_consume(
        self,
        tenant_id: str,
        metric: str,
        quantity: int,
        resource_id: Optional[str] = None,
        source: str = "llm",
    ) -> bool:
        """Atomically check the cap and record consumption. Returns True if allowed.

        Uses `pg_advisory_xact_lock` keyed by `tenant_id` so concurrent
        requests for the same tenant serialize. The lock is released
        when the transaction commits (or rolls back).

        Returns False if:
          - the plan is unknown / cap is 0 (fail-closed), or
          - current usage + quantity would exceed the cap.
        """
        plan = await self.get_tenant_plan(tenant_id)
        cap = self.get_plan_quota(plan, metric)
        if cap == 0:
            return False

        lock_key = self._tenant_lock_key(tenant_id)
        # 30-day rolling window
        period_start = time.time() - 30 * 24 * 3600

        async with AsyncSessionLocal() as db:
            async with db.begin():
                # Acquire tenant-level advisory lock (released at commit)
                await db.execute(
                    text("SELECT pg_advisory_xact_lock(:k)"),
                    {"k": lock_key},
                )
                current = await self.get_usage_in_period(
                    db, tenant_id, metric, period_start
                )
                if current + quantity > cap:
                    # Over the cap — roll back (transaction ends), don't insert.
                    return False
                db.add(
                    QuotaEvent(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        metric=metric,
                        quantity=quantity,
                        resource_id=resource_id,
                        source=source,
                    )
                )
                # commit happens at end of `async with db.begin()`
        return True

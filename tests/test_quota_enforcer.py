"""Verify atomic quota enforcement under concurrency.

The bug Phase 2 fixes: DbUsageMeter.check_quota() does SELECT SUM,
returns allowed=True, but a concurrent INSERT can land between
check and consume — both requests pass the cap, tenant goes over
their limit. Advisory lock + INSERT-then-SELECT is the fix.

DB-dependent tests (check_and_consume) are SKIPPED on SQLite since
`pg_advisory_xact_lock` is PostgreSQL-specific. The pure-data plan
quota tests run on every backend.
"""
import asyncio
import os

import pytest
import pytest_asyncio


# Skip the DB-backed concurrency tests when not running against PostgreSQL.
_REQUIRES_PG = pytest.mark.skipif(
    "postgres" not in os.environ.get("TEST_DATABASE_URL", ""),
    reason=(
        "Requires real PostgreSQL (pg_advisory_xact_lock). "
        "Set TEST_DATABASE_URL to a postgres+asyncpg URL to run."
    ),
)


# ---------------------------------------------------------------------------
# Pure-data tests (don't need DB) — always run
# ---------------------------------------------------------------------------


def test_get_plan_quota_free_tier():
    """Free tier: 10,000 tokens/month."""
    from nexus.services.quota_enforcer import QuotaEnforcer

    assert QuotaEnforcer.get_plan_quota("free", "tokens") == 10_000


def test_get_plan_quota_pro_tier():
    """Pro tier: 1,000,000 tokens/month."""
    from nexus.services.quota_enforcer import QuotaEnforcer

    assert QuotaEnforcer.get_plan_quota("pro", "tokens") == 1_000_000


# ---------------------------------------------------------------------------
# DB-dependent tests (require PostgreSQL)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def enforcer_with_db():
    """Yield a QuotaEnforcer + ensure quota_events table is present.

    Uses the global AsyncSessionLocal + the Base metadata create_all helper.
    """
    from nexus.db.database import AsyncSessionLocal, Base, engine

    # Make sure all tables (including the new quota_events) exist.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from nexus.services.quota_enforcer import QuotaEnforcer

    yield QuotaEnforcer(), AsyncSessionLocal


@_REQUIRES_PG
@pytest.mark.asyncio
async def test_check_quota_at_zero_always_passes(enforcer_with_db):
    """Tenant with 0 usage can always consume."""
    enforcer, _ = enforcer_with_db
    result = await enforcer.check_and_consume(
        tenant_id="test_tenant_zero", metric="tokens", quantity=1
    )
    assert result is True


@_REQUIRES_PG
@pytest.mark.asyncio
async def test_concurrent_check_quota_only_one_passes_at_limit(enforcer_with_db):
    """100 concurrent requests when tenant is at (cap-1) tokens used →
    exactly 1 passes, 99 fail. Without advisory lock, all 100 might
    pass the SELECT-then-INSERT race.
    """
    from nexus.services.quota_enforcer import QuotaEnforcer

    enforcer, _ = enforcer_with_db
    tenant_id = "test_tenant_concurrent"

    # Pre-consume up to (cap - 1) tokens. For free tier (cap = 10,000) we
    # consume 9,999 so only one more request can possibly succeed.
    cap = QuotaEnforcer.get_plan_quota("free", "tokens")
    for _ in range(cap - 1):
        await enforcer.record_usage(tenant_id=tenant_id, metric="tokens", quantity=1)

    # Concurrent 100 requests
    results = await asyncio.gather(*[
        enforcer.check_and_consume(tenant_id=tenant_id, metric="tokens", quantity=1)
        for _ in range(100)
    ])
    passed = sum(1 for r in results if r)
    assert passed == 1, f"Expected exactly 1 pass, got {passed}"

"""Behavioral RLS test — Task 1.4 (P0 defense-in-depth).

Opens two non-superuser sessions with different `app.tenant_id` and asserts
that cross-tenant SELECT returns 0 rows. Proves the migration is actually
enforcing RLS, not just declaring policies.

This test REQUIRES a real PostgreSQL with the `nexus_app` role created by
migration `add_row_level_security.py`. It is SKIPPED on SQLite (default
conftest) and on any TEST_DATABASE_URL that doesn't contain 'postgres'.

Why not S1-3's `test_rls_helper.py`:
  - test_rls_helper.py only checks the GUC injection helper + static
    SQL syntax of the migration. It cannot prove RLS actually blocks
    cross-tenant reads at runtime.
  - This file opens a real PG connection as `nexus_app` (NOSUPERUSER
    NOBYPASSRLS) and exercises the policy end-to-end.

Pre-conditions (must hold for test to pass):
  1. Migrations applied (add_row_level_security.py ran successfully)
  2. `nexus_app` role exists with login + a known password
  3. nexus_app has SELECT/INSERT/UPDATE/DELETE on the target tables
     (granted by the same migration)
  4. The `workflows` table has FORCE RLS + tenant_isolation policy

How to run (CI / local with docker compose):
  TEST_DATABASE_URL="postgresql+asyncpg://postgres:ChangeMe@2026!Secure@localhost:5433/nexus" \\
    alembic upgrade head
  TEST_DATABASE_URL="postgresql+asyncpg://nexus_app:TEMP_PLACEHOLDER_CHANGE_ME@localhost:5433/nexus" \\
    pytest tests/test_db_rls_behavioral.py -v
"""
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    "postgres" not in os.environ.get("TEST_DATABASE_URL", ""),
    reason=(
        "Requires real PostgreSQL with nexus_app role (NOSUPERUSER NOBYPASSRLS). "
        "Set TEST_DATABASE_URL to a postgres+asyncpg URL to run."
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _swap_user_to_nexus_app(url: str) -> str:
    """Replace the user in a postgresql URL with 'nexus_app'.

    Accepts the superuser URL used by the test runner's setup, and
    rewrites it to the non-superuser role. The password is irrelevant
    for the SKIP path (test won't run if URL isn't postgres) and is
    read from NEXUS_APP_DB_PASSWORD in the running path.
    """
    password = os.environ.get("NEXUS_APP_DB_PASSWORD", "TEMP_PLACEHOLDER_CHANGE_ME")
    # The original URL might be asyncpg://user:pass@host:port/db — we keep
    # host:port/db from the superuser URL, swap the credentials to nexus_app.
    # Format: scheme://user:password@host:port/dbname
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    netloc = f"nexus_app:{password}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    new = urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
    return new


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def two_tenant_sessions():
    """Two non-superuser sessions (nexus_app role), separate engines.

    Each engine keeps its own connection pool, so the GUC `app.tenant_id`
    set on one connection does not leak to the other. (Even with the same
    engine, asyncpg's pool would give us distinct connections, but two
    engines is the most robust way to be sure.)
    """
    base_url = os.environ["TEST_DATABASE_URL"]
    url_nexus_app = _swap_user_to_nexus_app(base_url)

    engine_a = create_async_engine(url_nexus_app, isolation_level="AUTOCOMMIT")
    engine_b = create_async_engine(url_nexus_app, isolation_level="AUTOCOMMIT")
    try:
        yield engine_a, engine_b
    finally:
        await engine_a.dispose()
        await engine_b.dispose()


@pytest_asyncio.fixture
async def two_real_tenants(two_tenant_sessions):
    """Create two real Tenant rows + one User so workflow FKs are satisfied.

    The `tenants` and `users` tables do NOT have RLS (see
    `add_row_level_security.py::MULTI_TENANT_TABLES`), so `nexus_app` can
    INSERT into them directly. The fixture yields three UUIDs:

      - tenant_a_id  → use for GUC when inserting the test workflow
      - tenant_b_id  → use for the cross-tenant GUC (verifier session)
      - user_id      → use as workflows.created_by (FK to users.id)

    Cleanup deletes the inserted rows in reverse-FK order.
    """
    engine_a, _ = two_tenant_sessions

    tenant_a_id = uuid.uuid4()
    tenant_b_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with engine_a.begin() as conn:
        # tenants has no RLS, FK from users.tenant_id → tenants.id.
        await conn.execute(
            text(
                """
                INSERT INTO tenants (id, name, slug, plan, status, created_at, updated_at)
                VALUES (:id, :name, :slug, 'free', 'active', NOW(), NOW()),
                       (:id2, :name2, :slug2, 'free', 'active', NOW(), NOW())
                """
            ),
            {
                "id": tenant_a_id,
                "name": "test_tenant_a",
                "slug": f"test-a-{tenant_a_id.hex[:8]}",
                "id2": tenant_b_id,
                "name2": "test_tenant_b",
                "slug2": f"test-b-{tenant_b_id.hex[:8]}",
            },
        )
        # users also has no RLS; FK to tenants.
        # Phase 3.7: use is_active (boolean) to match the actual users
        # table column. The previous status='active' assumed a `status`
        # text column that doesn't exist.
        await conn.execute(
            text(
                """
                INSERT INTO users (id, tenant_id, email, name, is_active, created_at, updated_at)
                VALUES (:id, :tid, :email, 'rls_test_user', true, NOW(), NOW())
                """
            ),
            {
                "id": user_id,
                "tid": tenant_a_id,
                "email": f"rls-{tenant_a_id.hex[:8]}@test.local",
            },
        )

    try:
        yield tenant_a_id, tenant_b_id, user_id
    finally:
        # Cleanup. The workflows row created by the test should already
        # be deleted in its own `finally` block, but be defensive here.
        async with engine_a.begin() as conn:
            # workflows has RLS — must set GUC to tenant_a before DELETE.
            await conn.execute(text(f"SET app.tenant_id = '{tenant_a_id}'"))
            await conn.execute(
                text("DELETE FROM workflows WHERE created_by = :uid"),
                {"uid": user_id},
            )
        async with engine_a.begin() as conn:
            # users / tenants have no RLS, no GUC needed.
            await conn.execute(
                text("DELETE FROM users WHERE id = :uid"), {"uid": user_id}
            )
            await conn.execute(
                text("DELETE FROM tenants WHERE id IN (:a, :b)"),
                {"a": tenant_a_id, "b": tenant_b_id},
            )


# ---------------------------------------------------------------------------
# Test: cross-tenant SELECT must return zero rows
# ---------------------------------------------------------------------------


async def test_cross_tenant_select_returns_zero_rows(
    two_tenant_sessions, two_real_tenants
):
    """Tenant A inserts a row; Tenant B's SELECT for it must return 0.

    If this fails, RLS is being bypassed (BYPASSRLS role, missing FORCE,
    or non-RLS connection). The most common cause historically: the app
    is connecting as the `nexus` superuser instead of `nexus_app`.
    """
    engine_a, engine_b = two_tenant_sessions
    tenant_a_id, tenant_b_id, user_id = two_real_tenants

    test_id = uuid.uuid4()

    # Insert as tenant_a: GUC == row.tenant_id (both real Tenant UUIDs),
    # so the RLS WITH CHECK clause lets the insert through. The cross-
    # tenant test then uses engine_b with GUC=tenant_b_id — the row
    # is invisible because row.tenant_id != current_setting.
    async with engine_a.begin() as conn:
        await conn.execute(text(f"SET app.tenant_id = '{tenant_a_id}'"))
        await conn.execute(
            text(
                """
                INSERT INTO workflows (id, tenant_id, created_by, name, config, created_at, updated_at)
                VALUES (:id, :tenant_id, :user_id, 'rls-behavioral-test', '{}'::jsonb, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                """
            ),
            {
                "id": test_id,
                "tenant_id": tenant_a_id,
                "user_id": user_id,
            },
        )

    try:
        # The cross-tenant check: GUC=tenant_b_id → row must be invisible.
        async with engine_b.begin() as conn:
            await conn.execute(text(f"SET app.tenant_id = '{tenant_b_id}'"))
            result = await conn.execute(
                text("SELECT COUNT(*) FROM workflows WHERE id = :id"),
                {"id": test_id},
            )
            count = result.scalar()
            assert count == 0, (
                f"RLS BYPASS DETECTED: tenant_b (GUC={tenant_b_id}) saw "
                f"{count} row(s) from tenant_a. The connected role is "
                f"probably a superuser, or FORCE RLS is missing. Verify "
                f"the migration ran and DATABASE_URL points to nexus_app."
            )

        # Sanity check: with the right GUC we CAN see the row.
        async with engine_a.begin() as conn:
            await conn.execute(text(f"SET app.tenant_id = '{tenant_a_id}'"))
            result = await conn.execute(
                text("SELECT COUNT(*) FROM workflows WHERE id = :id"),
                {"id": test_id},
            )
            count = result.scalar()
            assert count == 1, (
                f"Sanity check failed: tenant_a could not see its own row "
                f"(count={count}). RLS may be misconfigured."
            )
    finally:
        # Cleanup the workflow row (must use the owning tenant's GUC).
        async with engine_a.begin() as conn:
            await conn.execute(text(f"SET app.tenant_id = '{tenant_a_id}'"))
            await conn.execute(
                text("DELETE FROM workflows WHERE id = :id"), {"id": test_id}
            )


# ---------------------------------------------------------------------------
# Test: cross-tenant INSERT (WITH CHECK) is also blocked
# ---------------------------------------------------------------------------


async def test_cross_tenant_insert_is_blocked_by_with_check(
    two_tenant_sessions, two_real_tenants
):
    """WITH CHECK clause must reject rows whose tenant_id != GUC.

    Proves the second half of the policy (write side). Even if an attacker
    bypasses the USING clause, the WITH CHECK prevents them from
    inserting a row under a different tenant.
    """
    engine_a, _ = two_tenant_sessions
    tenant_a_id, tenant_b_id, user_id = two_real_tenants

    test_id = uuid.uuid4()

    async with engine_a.begin() as conn:
        # Set GUC to tenant_a, but try to insert a row with tenant_id =
        # tenant_b (both real Tenant UUIDs, FK satisfied). WITH CHECK
        # should reject this because row.tenant_id != current_setting.
        await conn.execute(text(f"SET app.tenant_id = '{tenant_a_id}'"))

        from sqlalchemy.exc import DBAPIError

        with pytest.raises(DBAPIError) as exc_info:
            await conn.execute(
                text(
                    """
                    INSERT INTO workflows (id, tenant_id, created_by, name, config, created_at, updated_at)
                    VALUES (:id, :tenant_id, :user_id, 'should-fail-rls', '{}'::jsonb, NOW(), NOW())
                    """
                ),
                {
                    "id": test_id,
                    "tenant_id": tenant_b_id,
                    "user_id": user_id,
                },
            )

        # The error message should mention RLS or the policy. PG raises
        # 'new row violates row-level security policy' for WITH CHECK
        # failures. We assert on the SQLSTATE class (42501 = insufficient
        # privilege, but RLS WITH CHECK actually raises '42501' too).
        assert "row-level security" in str(exc_info.value).lower() or "row level security" in str(exc_info.value).lower(), (
            f"Expected RLS WITH CHECK violation, got: {exc_info.value}"
        )


# ---------------------------------------------------------------------------
# Test: connecting role is NOT a superuser (the guard's premise)
# ---------------------------------------------------------------------------


async def test_connected_role_is_not_superuser(two_tenant_sessions):
    """The whole RLS story collapses if the connected role is a superuser.

    PG superusers implicitly BYPASSRLS — even FORCE RLS doesn't help.
    This test is the runtime equivalent of the lifespan guard.
    """
    engine_a, _ = two_tenant_sessions

    async with engine_a.connect() as conn:
        result = await conn.execute(
            text("SELECT current_user, current_setting('is_superuser') AS is_super")
        )
        row = result.first()
        assert row is not None
        current_user, is_super = row[0], row[1]
        assert is_super == "off", (
            f"Connected role '{current_user}' is a superuser. RLS will be "
            f"bypassed. The test must connect as 'nexus_app' (NOSUPERUSER). "
            f"Check TEST_DATABASE_URL swap logic in _swap_user_to_nexus_app."
        )
        assert current_user == "nexus_app", (
            f"Expected to connect as 'nexus_app', got '{current_user}'"
        )

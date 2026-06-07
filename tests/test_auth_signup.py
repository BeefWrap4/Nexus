"""Self-service signup tests.

POST /api/v1/auth/signup creates a Tenant and an admin User atomically
and returns a JWT. New customers can onboard without operator hand-seeding.

Covers the P0 no-self-service-signup blocker (Task 1.8).

Implementation note: We use a custom in-memory SQLite engine that creates
only the User + Tenant tables (mirroring the workaround in
tests/test_pii_audit_integration.py — system_settings uses JSONB which
SQLite can't render, so the conftest db_session fixture that builds
*all* tables blows up under SQLite).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from nexus.api.main import app
from nexus.db.database import Base, get_db
from nexus.models import Tenant, User
from nexus.security.auth import AuthService


# ---------------------------------------------------------------------------
# Module-scoped in-memory engine (only User + Tenant tables)
# ---------------------------------------------------------------------------

_TEST_ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
_TestSession = sessionmaker(_TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)


async def _override_get_db():
    async with _TestSession() as s:
        yield s


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _setup_db():
    """Create User + Tenant tables and override get_db for the duration of this module."""
    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[User.__table__, Tenant.__table__],
        )
    app.dependency_overrides[get_db] = _override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    await _TEST_ENGINE.dispose()


@pytest_asyncio.fixture
async def fresh_db():
    """Truncate User + Tenant between tests for isolation."""
    async with _TEST_ENGINE.begin() as conn:
        # SQLite doesn't have TRUNCATE; DELETE works (no FK cascade needed for these two)
        from sqlalchemy import text
        await conn.execute(text("DELETE FROM users"))
        await conn.execute(text("DELETE FROM tenants"))
    yield


@pytest_asyncio.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestSignupHappyPath:
    """Signup creates a tenant + admin user and returns a JWT."""

    @pytest.mark.asyncio
    async def test_signup_creates_tenant_and_admin(
        self, async_client: AsyncClient, fresh_db
    ):
        """POST /api/v1/auth/signup with new email/tenant_name/password
        creates a Tenant and an admin User, returns a JWT.
        """
        resp = await async_client.post(
            "/api/v1/auth/signup",
            json={
                "email": "newuser@example.com",
                "password": "StrongP@ss123",
                "tenant_name": "Acme Corp",
                "name": "New User",
            },
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        # Token returned
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 900

        # User shape
        user = data["user"]
        assert user["email"] == "newuser@example.com"
        assert user["name"] == "New User"
        assert user["role"] == "admin"
        assert user["tenant_id"] is not None

    @pytest.mark.asyncio
    async def test_signup_persists_tenant_and_user_in_db(
        self, async_client: AsyncClient, fresh_db
    ):
        """After signup, both the Tenant and User rows exist in the database."""
        from sqlalchemy import select

        resp = await async_client.post(
            "/api/v1/auth/signup",
            json={
                "email": "persist@example.com",
                "password": "StrongP@ss123",
                "tenant_name": "Persist Co",
                "name": "Persist User",
            },
        )
        assert resp.status_code == 201, resp.text
        user_payload = resp.json()["user"]
        tenant_id = user_payload["tenant_id"]

        async with _TestSession() as db:
            # Tenant exists
            tenant = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
            assert tenant.scalar_one_or_none() is not None

            # User exists with role=admin
            u = await db.execute(select(User).where(User.email == "persist@example.com"))
            user_row = u.scalar_one_or_none()
            assert user_row is not None
            assert user_row.role == "admin"
            assert user_row.is_active is True
            assert str(user_row.tenant_id) == tenant_id
            assert user_row.password_hash is not None
            assert user_row.password_hash != "StrongP@ss123"  # not plaintext

    @pytest.mark.asyncio
    async def test_signup_jwt_is_valid(self, async_client: AsyncClient, fresh_db):
        """The access_token returned from /signup is a valid JWT."""
        resp = await async_client.post(
            "/api/v1/auth/signup",
            json={
                "email": "jwt@example.com",
                "password": "StrongP@ss123",
                "tenant_name": "JWT Co",
                "name": "JWT User",
            },
        )
        assert resp.status_code == 201
        token = resp.json()["access_token"]
        payload = AuthService.verify_token(token)
        assert payload["type"] == "access"
        assert payload["role"] == "admin"
        assert payload["tenant_id"] == resp.json()["user"]["tenant_id"]


# ---------------------------------------------------------------------------
# Conflict / error cases
# ---------------------------------------------------------------------------


class TestSignupConflict:
    """Duplicate email returns 409."""

    @pytest.mark.asyncio
    async def test_duplicate_email_returns_409(
        self, async_client: AsyncClient, fresh_db
    ):
        """Re-signup with same email returns 409 conflict."""
        payload = {
            "email": "dupe@example.com",
            "password": "StrongP@ss123",
            "tenant_name": "Dupe Co",
            "name": "Dupe",
        }
        r1 = await async_client.post("/api/v1/auth/signup", json=payload)
        assert r1.status_code == 201, r1.text

        r2 = await async_client.post("/api/v1/auth/signup", json=payload)
        assert r2.status_code == 409
        assert "already" in r2.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestSignupValidation:
    """Invalid payloads are rejected before touching the DB."""

    @pytest.mark.asyncio
    async def test_missing_required_fields_returns_422(
        self, async_client: AsyncClient, fresh_db
    ):
        """Missing email/password/tenant_name returns 422."""
        resp = await async_client.post(
            "/api/v1/auth/signup",
            json={"email": "x@x.com"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_short_password_rejected(
        self, async_client: AsyncClient, fresh_db
    ):
        """Passwords shorter than 8 chars are rejected."""
        resp = await async_client.post(
            "/api/v1/auth/signup",
            json={
                "email": "short@example.com",
                "password": "abc",  # < 8 chars
                "tenant_name": "Short Co",
                "name": "Short",
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_email_rejected(
        self, async_client: AsyncClient, fresh_db
    ):
        """Invalid email format is rejected."""
        resp = await async_client.post(
            "/api/v1/auth/signup",
            json={
                "email": "not-an-email",
                "password": "StrongP@ss123",
                "tenant_name": "Bad Co",
                "name": "Bad",
            },
        )
        assert resp.status_code == 422

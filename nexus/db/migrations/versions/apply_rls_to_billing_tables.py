"""apply RLS to billing tables

Phase 3.7: the original ``add_row_level_security.py`` migration tried to
enable RLS on ``billing_subscriptions`` and ``billing_usage_records``,
but those tables are created by the later ``add_billing_tables``
migration. Running the original RLS migration on a fresh DB therefore
fails with ``UndefinedTableError``.

This migration applies the same RLS treatment to the billing tables
once they exist. Tenant isolation policy is identical to the one in
``add_row_level_security.py``.

Note: only ``subscriptions`` is created by ``add_billing_tables``.
``billing_usage_records`` is referenced by the ``BillingUsageRecord``
model but has no migration to create it — that's a pre-existing
gap tracked separately.

Revision ID: rls_billing_tables
Revises: add_billing_tables
Create Date: 2026-06-08
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "rls_billing_tables"
down_revision = "add_billing_tables"
branch_labels = None
depends_on = None


# Tables created by add_billing_tables.py that also need RLS.
BILLING_RLS_TABLES = [
    "subscriptions",
]


def upgrade() -> None:
    """Enable + FORCE RLS + tenant_isolation policy on billing tables."""
    for table in BILLING_RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id::text = current_setting('app.tenant_id', TRUE))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', TRUE))
            """
        )


def downgrade() -> None:
    """Remove RLS from billing tables (does not drop the tables)."""
    for table in BILLING_RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

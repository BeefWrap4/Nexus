"""add billing tables (subscriptions, invoices, quota_events)

Revision ID: add_billing_tables
Revises: audit_resource_id_nullable
Create Date: 2026-06-08

Phase 2.2: billing tables for Stripe subscription management.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "add_billing_tables"
down_revision = "audit_resource_id_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stripe_customer_id", sa.String(255), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column("plan", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("current_period_start", sa.DateTime, nullable=True),
        sa.Column("current_period_end", sa.DateTime, nullable=True),
        sa.Column("cancel_at_period_end", sa.String(10), nullable=False, server_default="false"),
        sa.Column("metadata", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_subscriptions_tenant_id", "subscriptions", ["tenant_id"])
    op.create_index("ix_subscriptions_stripe_customer_id", "subscriptions", ["stripe_customer_id"])
    op.create_index("ix_subscriptions_stripe_subscription_id", "subscriptions", ["stripe_subscription_id"])

    op.create_table(
        "invoices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.String(36), sa.ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("stripe_invoice_id", sa.String(255), nullable=True),
        sa.Column("amount_due_cents", sa.Integer, nullable=False),
        sa.Column("amount_paid_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("currency", sa.String(10), nullable=False, server_default="usd"),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("period_start", sa.DateTime, nullable=True),
        sa.Column("period_end", sa.DateTime, nullable=True),
        sa.Column("paid_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_invoices_tenant_id", "invoices", ["tenant_id"])
    op.create_index("ix_invoices_subscription_id", "invoices", ["subscription_id"])
    op.create_index("ix_invoices_stripe_invoice_id", "invoices", ["stripe_invoice_id"])

    op.create_table(
        "quota_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric", sa.String(50), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_quota_events_tenant_id", "quota_events", ["tenant_id"])
    op.create_index("ix_quota_events_created_at", "quota_events", ["created_at"])
    op.create_index("ix_quota_tenant_metric_created", "quota_events", ["tenant_id", "metric", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_quota_tenant_metric_created", "quota_events")
    op.drop_index("ix_quota_events_created_at", "quota_events")
    op.drop_index("ix_quota_events_tenant_id", "quota_events")
    op.drop_table("quota_events")
    op.drop_index("ix_invoices_stripe_invoice_id", "invoices")
    op.drop_index("ix_invoices_subscription_id", "invoices")
    op.drop_index("ix_invoices_tenant_id", "invoices")
    op.drop_table("invoices")
    op.drop_index("ix_subscriptions_stripe_subscription_id", "subscriptions")
    op.drop_index("ix_subscriptions_stripe_customer_id", "subscriptions")
    op.drop_index("ix_subscriptions_tenant_id", "subscriptions")
    op.drop_table("subscriptions")

"""add billing_usage_records table (Phase 4.7)

Revision ID: add_billing_usage_records
Revises: apply_rls_to_billing_tables
Create Date: 2026-06-07

修复 pre-existing issue: nexus/models/billing.py:BillingUsageRecord
引用了 `billing_usage_records` 表, 但没有任何 migration 创建它。
DbUsageMeter.record_usage() / get_usage() 在第一次调用时会
table-doesn't-exist 崩溃。

修复: 创建该表 (与 Phase 2.2 的 quota_events 是不同设计 — billing_usage_records
是 billing 模块的 legacy 设计, quota_events 是 Phase 2 新的事实源。
两者并存, 后续可统一)。
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "add_billing_usage_records"
down_revision = "rls_billing_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_usage_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric", sa.String(50), nullable=False),
        sa.Column("value", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_billing_usage_records_tenant_id", "billing_usage_records", ["tenant_id"])
    op.create_index("ix_billing_usage_records_recorded_at", "billing_usage_records", ["recorded_at"])


def downgrade() -> None:
    op.drop_index("ix_billing_usage_records_recorded_at", "billing_usage_records")
    op.drop_index("ix_billing_usage_records_tenant_id", "billing_usage_records")
    op.drop_table("billing_usage_records")

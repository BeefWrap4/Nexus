"""make audit_logs.resource_id nullable

Revision ID: audit_resource_id_nullable
Revises: merge_ss_wf_runs
Create Date: 2026-06-07

P2 fix: audit_middleware._parse_resource_id used to fall back to
UUID(int=0) = '00000000-0000-0000-0000-000000000000' for non-UUID
resource IDs (e.g. /api/v1/prompts/list/clone). That sentinel
corrupted per-resource audit queries — all such rows shared the same
null UUID, losing referential integrity for "which row was touched".

Now AuditLog.resource_id is nullable=True, and the middleware returns
None instead of UUID(int=0). This migration aligns the existing
schema with the model change for databases that were created before
the fix.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "audit_resource_id_nullable"
down_revision = "merge_ss_wf_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "audit_logs",
        "resource_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "audit_logs",
        "resource_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )

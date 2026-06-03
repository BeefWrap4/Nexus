"""Allow inline workflow runs without a workflow_id.

Revision ID: wf_runs_workflow_id_nullable
Revises: seed_data
Create Date: 2026-06-04
"""

from alembic import op
import sqlalchemy as sa


revision = "wf_runs_workflow_id_nullable"
down_revision = "seed_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "wf_runs",
        "workflow_id",
        existing_type=sa.UUID(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "wf_runs",
        "workflow_id",
        existing_type=sa.UUID(),
        nullable=False,
    )

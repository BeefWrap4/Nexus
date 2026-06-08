"""merge ss_wf_runs (stub migration to restore alembic chain)

Revision ID: merge_ss_wf_runs
Revises: add_system_settings, wf_runs_workflow_id_nullable
Create Date: 2026-06-07

迁移历史链修复: filter-repo 把这个 merge 节点丢了, 但 down_revision
链 (audit_resource_id_nullable → merge_ss_wf_runs) 仍然引用它。
这是个空 merge (no-op), 作用是恢复 alembic 链完整性。

实际 DB 状态: 已经走过这个 revision (head = add_billing_usage_records),
所以 upgrade()/downgrade() 都是 no-op。
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401


# revision identifiers, used by Alembic.
revision = "merge_ss_wf_runs"
down_revision = ("system_settings", "wf_runs_workflow_id_nullable")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

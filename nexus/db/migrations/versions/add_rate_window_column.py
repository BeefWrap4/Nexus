"""add rate_window to api_keys and missing indexes

Revision ID: 54087a739c6b
Revises: wf_runs_workflow_id_nullable
Create Date: 2026-06-04

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '54087a739c6b'
down_revision = 'seed_data'
branch_labels = None
depends_on = None


def _create_index_if_not_exists(index_name: str, table_name: str, columns: list[str]) -> None:
    """Create index only if it doesn't already exist.

    Phase 3.7: The original op.create_index calls failed on a fresh DB
    because initial_migration.py already creates some of these same
    indexes (e.g. ix_checkpoints_run_id). Use raw SQL with IF NOT EXISTS
    so the migration is idempotent regardless of which path created
    the index first.
    """
    cols = ", ".join(columns)
    op.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({cols})")


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    op.execute(f"DROP INDEX IF EXISTS {table_name}.{index_name}")


def upgrade():
    # Add rate_window column to api_keys
    op.add_column('api_keys', sa.Column('rate_window', sa.Integer(), nullable=True, server_default='60'))

    # Add missing indexes for checkpoints
    _create_index_if_not_exists('ix_checkpoints_created_at', 'checkpoints', ['created_at'])
    _create_index_if_not_exists('ix_checkpoints_run_id', 'checkpoints', ['run_id'])
    _create_index_if_not_exists('ix_checkpoints_run_node', 'checkpoints', ['run_id', 'node_id'])

    # Add missing indexes for dead_letter_jobs
    _create_index_if_not_exists('ix_dead_letter_failed_at', 'dead_letter_jobs', ['failed_at'])
    _create_index_if_not_exists('ix_dead_letter_run_id', 'dead_letter_jobs', ['run_id'])
    _create_index_if_not_exists('ix_dead_letter_status', 'dead_letter_jobs', ['status'])
    _create_index_if_not_exists('ix_dead_letter_tenant_id', 'dead_letter_jobs', ['tenant_id'])

    # Add missing indexes for llm_call_traces
    _create_index_if_not_exists('ix_llm_traces_agent_node', 'llm_call_traces', ['agent_id', 'node_id'])
    _create_index_if_not_exists('ix_llm_traces_cache_hit', 'llm_call_traces', ['cache_hit'])
    _create_index_if_not_exists('ix_llm_traces_created_at', 'llm_call_traces', ['created_at'])
    _create_index_if_not_exists('ix_llm_traces_model_provider', 'llm_call_traces', ['model', 'provider'])
    _create_index_if_not_exists('ix_llm_traces_tenant_run', 'llm_call_traces', ['tenant_id', 'run_id'])


def downgrade():
    op.drop_column('api_keys', 'rate_window')

    _drop_index_if_exists('ix_llm_traces_tenant_run', 'llm_call_traces')
    _drop_index_if_exists('ix_llm_traces_model_provider', 'llm_call_traces')
    _drop_index_if_exists('ix_llm_traces_created_at', 'llm_call_traces')
    _drop_index_if_exists('ix_llm_traces_cache_hit', 'llm_call_traces')
    _drop_index_if_exists('ix_llm_traces_agent_node', 'llm_call_traces')

    _drop_index_if_exists('ix_dead_letter_tenant_id', 'dead_letter_jobs')
    _drop_index_if_exists('ix_dead_letter_status', 'dead_letter_jobs')
    _drop_index_if_exists('ix_dead_letter_run_id', 'dead_letter_jobs')
    _drop_index_if_exists('ix_dead_letter_failed_at', 'dead_letter_jobs')

    _drop_index_if_exists('ix_checkpoints_run_node', 'checkpoints')
    _drop_index_if_exists('ix_checkpoints_run_id', 'checkpoints')
    _drop_index_if_exists('ix_checkpoints_created_at', 'checkpoints')

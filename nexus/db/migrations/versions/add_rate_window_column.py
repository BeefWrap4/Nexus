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


def upgrade():
    # Add rate_window column to api_keys
    op.add_column('api_keys', sa.Column('rate_window', sa.Integer(), nullable=True, server_default='60'))

    # Add missing indexes for checkpoints
    op.create_index('ix_checkpoints_created_at', 'checkpoints', ['created_at'])
    op.create_index('ix_checkpoints_run_id', 'checkpoints', ['run_id'])
    op.create_index('ix_checkpoints_run_node', 'checkpoints', ['run_id', 'node_id'])

    # Add missing indexes for dead_letter_jobs
    op.create_index('ix_dead_letter_failed_at', 'dead_letter_jobs', ['failed_at'])
    op.create_index('ix_dead_letter_run_id', 'dead_letter_jobs', ['run_id'])
    op.create_index('ix_dead_letter_status', 'dead_letter_jobs', ['status'])
    op.create_index('ix_dead_letter_tenant_id', 'dead_letter_jobs', ['tenant_id'])

    # Add missing indexes for llm_call_traces
    op.create_index('ix_llm_traces_agent_node', 'llm_call_traces', ['agent_id', 'node_id'])
    op.create_index('ix_llm_traces_cache_hit', 'llm_call_traces', ['cache_hit'])
    op.create_index('ix_llm_traces_created_at', 'llm_call_traces', ['created_at'])
    op.create_index('ix_llm_traces_model_provider', 'llm_call_traces', ['model', 'provider'])
    op.create_index('ix_llm_traces_tenant_run', 'llm_call_traces', ['tenant_id', 'run_id'])


def downgrade():
    op.drop_column('api_keys', 'rate_window')

    op.drop_index('ix_llm_traces_tenant_run', 'llm_call_traces')
    op.drop_index('ix_llm_traces_model_provider', 'llm_call_traces')
    op.drop_index('ix_llm_traces_created_at', 'llm_call_traces')
    op.drop_index('ix_llm_traces_cache_hit', 'llm_call_traces')
    op.drop_index('ix_llm_traces_agent_node', 'llm_call_traces')

    op.drop_index('ix_dead_letter_tenant_id', 'dead_letter_jobs')
    op.drop_index('ix_dead_letter_status', 'dead_letter_jobs')
    op.drop_index('ix_dead_letter_run_id', 'dead_letter_jobs')
    op.drop_index('ix_dead_letter_failed_at', 'dead_letter_jobs')

    op.drop_index('ix_checkpoints_run_node', 'checkpoints')
    op.drop_index('ix_checkpoints_run_id', 'checkpoints')
    op.drop_index('ix_checkpoints_created_at', 'checkpoints')

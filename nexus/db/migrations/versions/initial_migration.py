"""Initial migration for nexus database.

Revision ID: initial_migration
Revises:
Create Date: 2026-06-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'initial_migration'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── tenants ──
    op.create_table(
        'tenants',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False, unique=True),
        sa.Column('plan', sa.String(50), nullable=False, server_default='free'),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_tenants_slug', 'tenants', ['slug'], unique=True)

    # ── users ──
    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', sa.UUID(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('role', sa.String(50), nullable=False, server_default='member'),
        sa.Column('avatar_url', sa.Text(), nullable=True),
        sa.Column('password_hash', sa.String(255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_unique_constraint('uq_user_email', 'users', ['tenant_id', 'email'])
    op.create_index('ix_users_tenant_id', 'users', ['tenant_id'])

    # ── api_keys ──
    op.create_table(
        'api_keys',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', sa.UUID(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('key_prefix', sa.String(20), nullable=False),
        sa.Column('key_hash', sa.String(255), nullable=False),
        sa.Column('permissions', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('rate_limit', sa.Integer(), nullable=False, server_default='1000'),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_api_keys_tenant_id', 'api_keys', ['tenant_id'])
    op.create_index('ix_api_keys_user_id', 'api_keys', ['user_id'])

    # ── workflows ──
    op.create_table(
        'workflows',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', sa.UUID(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by', sa.UUID(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('variables', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('current_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('run_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('schedule_cron', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_workflows_tenant_id', 'workflows', ['tenant_id'])

    # ── wf_versions ──
    op.create_table(
        'wf_versions',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('workflow_id', sa.UUID(), sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('change_notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.UUID(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_unique_constraint('uq_wf_versions_workflow_version', 'wf_versions', ['workflow_id', 'version'])
    op.create_index('ix_wf_versions_workflow_id', 'wf_versions', ['workflow_id'])

    # ── wf_runs ──
    op.create_table(
        'wf_runs',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', sa.UUID(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workflow_id', sa.UUID(), sa.ForeignKey('workflows.id'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('trigger_type', sa.String(50), nullable=True),
        sa.Column('trigger_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('state', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_wf_runs_tenant_id', 'wf_runs', ['tenant_id'])
    op.create_index('ix_wf_runs_workflow_id', 'wf_runs', ['workflow_id'])
    op.create_index('ix_wf_runs_status', 'wf_runs', ['status'])

    # ── node_runs ──
    op.create_table(
        'node_runs',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('wf_run_id', sa.UUID(), sa.ForeignKey('wf_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('node_id', sa.String(100), nullable=False),
        sa.Column('node_type', sa.String(50), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('input', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('output', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_node_runs_wf_run_id', 'node_runs', ['wf_run_id'])
    op.create_index('ix_node_runs_node_id', 'node_runs', ['node_id'])

    # ── prompt_templates ──
    op.create_table(
        'prompt_templates',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', sa.UUID(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('template_type', sa.String(50), nullable=False, server_default='system'),
        sa.Column('current_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_by', sa.UUID(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_prompt_templates_tenant_id', 'prompt_templates', ['tenant_id'])

    # ── prompt_template_versions ──
    op.create_table(
        'prompt_template_versions',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('template_id', sa.UUID(), sa.ForeignKey('prompt_templates.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('variables', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('change_notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.UUID(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_prompt_template_versions_template_id', 'prompt_template_versions', ['template_id'])
    op.create_unique_constraint('uq_prompt_template_version', 'prompt_template_versions', ['template_id', 'version'])

    # ── agents ──
    op.create_table(
        'agents',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', sa.UUID(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('role', sa.String(255), nullable=True),
        sa.Column('goal', sa.Text(), nullable=True),
        sa.Column('backstory', sa.Text(), nullable=True),
        sa.Column('llm_settings', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('system_prompt', sa.Text(), nullable=True),
        sa.Column('system_prompt_template_id', sa.UUID(), sa.ForeignKey('prompt_templates.id', ondelete='SET NULL'), nullable=True),
        sa.Column('tools', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('memory_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('max_iterations', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_agents_tenant_id', 'agents', ['tenant_id'])
    op.create_index('ix_agents_tenant_name', 'agents', ['tenant_id', 'name'])

    # ── tools ──
    op.create_table(
        'tools',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', sa.UUID(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('schema', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('auth_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_tools_tenant_id', 'tools', ['tenant_id'])

    # ── hitl_tasks ──
    op.create_table(
        'hitl_tasks',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', sa.UUID(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('wf_run_id', sa.UUID(), sa.ForeignKey('wf_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('node_id', sa.String(100), nullable=False),
        sa.Column('assignee_id', sa.UUID(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('task_type', sa.String(50), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('response', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('deadline', sa.DateTime(timezone=True), nullable=True),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_hitl_tasks_tenant_id', 'hitl_tasks', ['tenant_id'])
    op.create_index('ix_hitl_tasks_wf_run_id', 'hitl_tasks', ['wf_run_id'])
    op.create_index('ix_hitl_tasks_assignee_id', 'hitl_tasks', ['assignee_id'])
    op.create_index('ix_hitl_tasks_status', 'hitl_tasks', ['status'])

    # ── audit_logs ──
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', sa.UUID(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('resource_type', sa.String(50), nullable=False),
        sa.Column('resource_id', sa.UUID(), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_audit_logs_tenant_id', 'audit_logs', ['tenant_id'])
    op.create_index('ix_audit_logs_user_id', 'audit_logs', ['user_id'])
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])

    # ── artifacts ──
    op.create_table(
        'artifacts',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', sa.UUID(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('wf_run_id', sa.UUID(), sa.ForeignKey('wf_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('node_id', sa.String(100), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('file_path', sa.Text(), nullable=True),
        sa.Column('mime_type', sa.String(100), nullable=True),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_artifacts_tenant_id', 'artifacts', ['tenant_id'])
    op.create_index('ix_artifacts_wf_run_id', 'artifacts', ['wf_run_id'])

    # ── crews ──
    op.create_table(
        'crews',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', sa.UUID(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('mode', sa.String(50), nullable=False, server_default='hierarchical'),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_crews_tenant_id', 'crews', ['tenant_id'])
    op.create_index('ix_crews_tenant_mode', 'crews', ['tenant_id', 'mode'])

    # ── crew_agents ──
    op.create_table(
        'crew_agents',
        sa.Column('crew_id', sa.UUID(), sa.ForeignKey('crews.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('agent_id', sa.UUID(), sa.ForeignKey('agents.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('role_in_crew', sa.String(50), nullable=False, server_default='worker'),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
    )

    # ── crew_runs ──
    op.create_table(
        'crew_runs',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('crew_id', sa.UUID(), sa.ForeignKey('crews.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('input_task', sa.Text(), nullable=True),
        sa.Column('output', sa.Text(), nullable=True),
        sa.Column('worker_results', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('duration_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_crew_runs_crew_id', 'crew_runs', ['crew_id'])
    op.create_index('ix_crew_runs_crew_status', 'crew_runs', ['crew_id', 'status'])
    op.create_index('ix_crew_runs_tenant_status', 'crew_runs', ['tenant_id', 'status'])

    # ── eval_runs ──
    op.create_table(
        'eval_runs',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('eval_type', sa.String(50), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('dataset', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('results', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_eval_runs_tenant_id', 'eval_runs', ['tenant_id'])

    # ── llm_call_traces ──
    op.create_table(
        'llm_call_traces',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('run_id', sa.UUID(), sa.ForeignKey('wf_runs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('node_id', sa.String(100), nullable=True),
        sa.Column('agent_id', sa.String(100), nullable=True),
        sa.Column('experiment_id', sa.UUID(), nullable=True),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('provider', sa.String(50), nullable=True),
        sa.Column('system_prompt', sa.Text(), nullable=True),
        sa.Column('user_prompt', sa.Text(), nullable=True),
        sa.Column('response_content', sa.Text(), nullable=True),
        sa.Column('response_reasoning', sa.Text(), nullable=True),
        sa.Column('tool_calls', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('prompt_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('completion_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('latency_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('fallback_model', sa.String(100), nullable=True),
        sa.Column('cache_hit', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('raw_response', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_llm_call_traces_run_id', 'llm_call_traces', ['run_id'])
    op.create_index('ix_llm_call_traces_tenant_id', 'llm_call_traces', ['tenant_id'])
    op.create_index('ix_llm_call_traces_created_at', 'llm_call_traces', ['created_at'])

    # ── checkpoints ──
    op.create_table(
        'checkpoints',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('run_id', sa.UUID(), sa.ForeignKey('wf_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('node_id', sa.String(100), nullable=True),
        sa.Column('state_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('state_s3_key', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_checkpoints_run_id', 'checkpoints', ['run_id'])

    # ── dead_letter_jobs ──
    op.create_table(
        'dead_letter_jobs',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('workflow_id', sa.UUID(), nullable=True),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('error_type', sa.String(100), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('traceback', sa.Text(), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='failed'),
        sa.Column('failed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('retried_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_dead_letter_jobs_tenant_id', 'dead_letter_jobs', ['tenant_id'])
    op.create_index('ix_dead_letter_jobs_status', 'dead_letter_jobs', ['status'])

    # ── prompt_experiments ──
    op.create_table(
        'prompt_experiments',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('template_id', sa.UUID(), sa.ForeignKey('prompt_templates.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='running'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_prompt_experiments_tenant_id', 'prompt_experiments', ['tenant_id'])
    op.create_index('ix_prompt_experiments_template_id', 'prompt_experiments', ['template_id'])

    # ── prompt_experiment_variants ──
    op.create_table(
        'prompt_experiment_variants',
        sa.Column('id', sa.UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('experiment_id', sa.UUID(), sa.ForeignKey('prompt_experiments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('template_version', sa.Integer(), nullable=False),
        sa.Column('traffic_percentage', sa.Integer(), nullable=False),
        sa.Column('total_calls', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avg_latency_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avg_tokens', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_index('ix_prompt_experiment_variants_experiment_id', 'prompt_experiment_variants', ['experiment_id'])


def downgrade() -> None:
    op.drop_table('prompt_experiment_variants')
    op.drop_table('prompt_experiments')
    op.drop_table('dead_letter_jobs')
    op.drop_table('checkpoints')
    op.drop_table('llm_call_traces')
    op.drop_table('eval_runs')
    op.drop_table('crew_runs')
    op.drop_table('crew_agents')
    op.drop_table('crews')
    op.drop_table('artifacts')
    op.drop_table('audit_logs')
    op.drop_table('hitl_tasks')
    op.drop_table('tools')
    op.drop_table('agents')
    op.drop_table('prompt_template_versions')
    op.drop_table('prompt_templates')
    op.drop_table('node_runs')
    op.drop_table('wf_runs')
    op.drop_table('wf_versions')
    op.drop_table('workflows')
    op.drop_table('api_keys')
    op.drop_table('users')
    op.drop_table('tenants')

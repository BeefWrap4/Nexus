"""add system_settings KV table

Revision ID: system_settings
Revises: 54087a739c6b
Create Date: 2026-06-07

修复 (P1 收尾): settings.py 的 /api/v1/settings/{general,llm,security} 之前
是 stub (只 log 不入库), 没法让前端"保存设置"真的工作。加 system_settings
KV 表 (tenant-scoped, JSONB value, category 标签)。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'system_settings'
# 接到当前 head (rls_policies_001) 之后, 保持单一 head 链
down_revision = 'rls_policies_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'system_settings',
        # 修复: tenants.id 和 users.id 在 DB 里是 varchar(36) (不是 UUID),
        # 用 UUID 类型创建 FK 会失败 "Key columns tenant_id and id are
        # of incompatible types: uuid and character varying"。改成 String(36)
        # 跟其它表 (api_keys / wf_runs) 一致
        sa.Column('tenant_id', sa.String(36),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'),
                  primary_key=True, nullable=False),
        sa.Column('key', sa.String(255), primary_key=True, nullable=False),
        sa.Column('value', postgresql.JSONB, nullable=False),
        sa.Column('category', sa.String(50), nullable=False, server_default='general'),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column('updated_by', sa.String(36),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
    )
    # 按 (tenant_id, category) 列快 — Settings.vue 按 category 拉
    op.create_index('ix_system_settings_tenant_category',
                    'system_settings', ['tenant_id', 'category'])
    # RLS: 跟其它表一样开 (row-level security)
    op.execute("ALTER TABLE system_settings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE system_settings FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON system_settings
        USING (tenant_id::text = current_setting('app.tenant_id', TRUE))
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON system_settings")
    op.drop_index('ix_system_settings_tenant_category', table_name='system_settings')
    op.drop_table('system_settings')

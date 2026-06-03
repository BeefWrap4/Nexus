"""Seed data migration for nexus database.

Revision ID: seed_data
Revises: initial_migration
Create Date: 2026-06-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'seed_data'
down_revision = 'initial_migration'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    agent_columns = {column["name"] for column in inspector.get_columns("agents")}
    if "llm_settings" not in agent_columns and "model_config" in agent_columns:
        op.alter_column("agents", "model_config", new_column_name="llm_settings")
        agent_columns.remove("model_config")
        agent_columns.add("llm_settings")

    if "llm_settings" not in agent_columns:
        op.add_column(
            "agents",
            sa.Column(
                "llm_settings",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="{}",
            ),
        )
    elif bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "ALTER TABLE agents ALTER COLUMN llm_settings TYPE jsonb "
                "USING llm_settings::jsonb"
            )
        )
        op.execute(
            sa.text("ALTER TABLE agents ALTER COLUMN llm_settings SET DEFAULT '{}'")
        )

    # Insert default tenant
    op.execute(
        sa.text("""
        INSERT INTO tenants (id, name, slug, plan, config, status, created_at, updated_at)
        VALUES (
            gen_random_uuid(),
            'Default Tenant',
            'default',
            'free',
            '{"theme": "default", "features": {"workflows": true, "agents": true, "tools": true}}',
            'active',
            now(),
            now()
        )
        ON CONFLICT (slug) DO NOTHING;
        """)
    )

    # Insert default admin user (password should be changed immediately)
    # Password hash placeholder - use a proper hashing mechanism in production
    op.execute(
        sa.text("""
        INSERT INTO users (id, tenant_id, email, name, role, password_hash, is_active, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            t.id,
            'admin@nexus.local',
            'admin',
            'admin',
            '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW',  -- placeholder hash
            true,
            now(),
            now()
        FROM tenants t
        WHERE t.slug = 'default'
        ON CONFLICT ON CONSTRAINT uq_user_email DO NOTHING;
        """)
    )

    # Insert sample workflow definition
    op.execute(
        sa.text("""
        INSERT INTO workflows (id, tenant_id, name, description, status, config, created_by, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            t.id,
            'Hello World Workflow',
            'A simple starter workflow to demonstrate the system.',
            'draft',
            '{"nodes": [], "edges": []}',
            u.id,
            now(),
            now()
        FROM tenants t
        JOIN users u ON u.tenant_id = t.id
        WHERE t.slug = 'default'
          AND u.name = 'admin'
          AND NOT EXISTS (
              SELECT 1
              FROM workflows w
              WHERE w.tenant_id = t.id
                AND w.name = 'Hello World Workflow'
          );
        """)
    )

    # Insert sample agent
    op.execute(
        sa.text("""
        INSERT INTO agents (id, tenant_id, name, role, goal, backstory, llm_settings, tools, memory_config, max_iterations, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            t.id,
            'Default Agent',
            'General Assistant',
            'Assist with general workflow tasks and provide helpful responses.',
            'A versatile AI assistant trained to handle a variety of tasks.',
            '{"model": "gpt-4", "temperature": 0.7, "max_tokens": 2048}',
            '[]',
            '{}',
            10,
            now(),
            now()
        FROM tenants t
        WHERE t.slug = 'default'
          AND NOT EXISTS (
              SELECT 1
              FROM agents a
              WHERE a.tenant_id = t.id
                AND a.name = 'Default Agent'
          );
        """)
    )

    # Insert sample tool
    op.execute(
        sa.text("""
        INSERT INTO tools (id, tenant_id, name, description, type, config, schema, auth_config, status, created_at)
        SELECT
            gen_random_uuid(),
            t.id,
            'HTTP Request',
            'Make HTTP requests to external APIs.',
            'http',
            '{"timeout": 30, "retry_count": 3}',
            '{"type": "object", "properties": {"url": {"type": "string"}, "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]}, "headers": {"type": "object"}, "body": {"type": "object"}}, "required": ["url", "method"]}',
            null,
            'active',
            now()
        FROM tenants t
        WHERE t.slug = 'default'
          AND NOT EXISTS (
              SELECT 1
              FROM tools tools_existing
              WHERE tools_existing.tenant_id = t.id
                AND tools_existing.name = 'HTTP Request'
          );
        """)
    )


def downgrade() -> None:
    # Remove seeded data in reverse order
    op.execute(sa.text("DELETE FROM tools WHERE tenant_id IN (SELECT id FROM tenants WHERE slug = 'default');"))
    op.execute(sa.text("DELETE FROM agents WHERE tenant_id IN (SELECT id FROM tenants WHERE slug = 'default');"))
    op.execute(sa.text("DELETE FROM workflows WHERE tenant_id IN (SELECT id FROM tenants WHERE slug = 'default');"))
    op.execute(sa.text("DELETE FROM users WHERE tenant_id IN (SELECT id FROM tenants WHERE slug = 'default');"))
    op.execute(sa.text("DELETE FROM tenants WHERE slug = 'default';"))

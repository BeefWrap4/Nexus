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
    # Insert default tenant
    op.execute(
        sa.text("""
        INSERT INTO tenants (id, name, slug, description, config, status, created_at, updated_at)
        VALUES (
            gen_random_uuid(),
            'Default Tenant',
            'default',
            'Default tenant created during initial setup.',
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
        INSERT INTO users (id, tenant_id, email, username, hashed_password, full_name, role, status, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            t.id,
            'admin@nexus.local',
            'admin',
            '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW',  -- placeholder hash
            'System Administrator',
            'admin',
            'active',
            now(),
            now()
        FROM tenants t
        WHERE t.slug = 'default'
        ON CONFLICT (email) DO NOTHING;
        """)
    )

    # Insert sample workflow definition
    op.execute(
        sa.text("""
        INSERT INTO workflows (id, tenant_id, name, description, status, created_by, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            t.id,
            'Hello World Workflow',
            'A simple starter workflow to demonstrate the system.',
            'draft',
            u.id,
            now(),
            now()
        FROM tenants t
        JOIN users u ON u.tenant_id = t.id
        WHERE t.slug = 'default' AND u.username = 'admin'
        ON CONFLICT DO NOTHING;
        """)
    )

    # Insert sample agent
    op.execute(
        sa.text("""
        INSERT INTO agents (id, tenant_id, name, description, agent_type, config, status, created_by, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            t.id,
            'Default Agent',
            'General-purpose agent for workflow execution.',
            'default',
            '{"model": "gpt-4", "temperature": 0.7, "max_tokens": 2048}',
            'active',
            u.id,
            now(),
            now()
        FROM tenants t
        JOIN users u ON u.tenant_id = t.id
        WHERE t.slug = 'default' AND u.username = 'admin'
        ON CONFLICT DO NOTHING;
        """)
    )

    # Insert sample tool
    op.execute(
        sa.text("""
        INSERT INTO tools (id, tenant_id, name, description, tool_type, schema, implementation, config, status, created_by, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            t.id,
            'HTTP Request',
            'Make HTTP requests to external APIs.',
            'http',
            '{"type": "object", "properties": {"url": {"type": "string"}, "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]}, "headers": {"type": "object"}, "body": {"type": "object"}}, "required": ["url", "method"]}',
            null,
            '{"timeout": 30, "retry_count": 3}',
            'active',
            u.id,
            now(),
            now()
        FROM tenants t
        JOIN users u ON u.tenant_id = t.id
        WHERE t.slug = 'default' AND u.username = 'admin'
        ON CONFLICT DO NOTHING;
        """)
    )


def downgrade() -> None:
    # Remove seeded data in reverse order
    op.execute(sa.text("DELETE FROM tools WHERE tenant_id IN (SELECT id FROM tenants WHERE slug = 'default');"))
    op.execute(sa.text("DELETE FROM agents WHERE tenant_id IN (SELECT id FROM tenants WHERE slug = 'default');"))
    op.execute(sa.text("DELETE FROM workflows WHERE tenant_id IN (SELECT id FROM tenants WHERE slug = 'default');"))
    op.execute(sa.text("DELETE FROM users WHERE tenant_id IN (SELECT id FROM tenants WHERE slug = 'default');"))
    op.execute(sa.text("DELETE FROM tenants WHERE slug = 'default';"))

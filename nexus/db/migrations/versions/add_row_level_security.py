"""add Row-Level Security on multi-tenant tables

修复 (S1-3): 之前 README/P0 报告说 "PostgreSQL RLS + 端点级租户过滤"，
但全仓库 grep 不到任何 `ENABLE ROW LEVEL SECURITY` 或 `CREATE POLICY`。
应用层 WHERE 漏一个 = 跨租户数据泄露。修复：用 Alembic 迁移真正启用 RLS。

策略：
1. 创建一个非 superuser 的应用角色 nexus_app（不显式 BYPASSRLS）
2. 对每个 multi-tenant 表 ENABLE + FORCE RLS（superuser 也要走 RLS）
3. CREATE POLICY tenant_isolation：行 tenant_id = current_setting('app.tenant_id') 时可见
4. GUC `app.tenant_id` 由 nexus/db/database.py 的 SQLAlchemy event hook 在事务开始时设置
5. tenants 表不应用 RLS（它是 parent，否则查 tenants 永远空集）

⚠️ 部署注意：
- 应用必须用 nexus_app 角色连 DB（不是 nexus superuser），否则 RLS 被 bypassrls 旁路
- compose 里设 DATABASE_URL=postgresql://nexus_app:密码@host/nexus
- 或者用 PGBouncer 之类代理，自动切到 nexus_app

down_revision: 54087a739c6b (seed_data)
"""
import os

from alembic import op

# revision identifiers, used by Alembic.
revision = "rls_policies_001"
down_revision = "54087a739c6b"
branch_labels = None
depends_on = None


# 修复 (S1-3): 所有 multi-tenant 表（不含 tenants 本身）
# 与 nexus/models/* 保持同步
MULTI_TENANT_TABLES = [
    "agents",
    "api_keys",
    "artifacts",
    "auditlogs",
    "billing_subscriptions",
    "billing_usage_records",
    "crew_agents",
    "crews",
    "eval_runs",
    "hitl_tasks",
    "llm_call_traces",
    "node_runs",
    "prompt_experiments",
    "prompt_templates",
    "tools",
    "wf_versions",
    "workflows",
]


# 修复 (S1-3): 应用角色，从环境变量读密码（默认 16 字节 hex）
# 生产部署必须设 NEXUS_APP_DB_PASSWORD，否则迁移会用一个临时密码（会写日志警告）
APP_DB_PASSWORD = os.environ.get("NEXUS_APP_DB_PASSWORD", "TEMP_PLACEHOLDER_CHANGE_ME")


def upgrade() -> None:
    """1) 创建 nexus_app 角色（不 BYPASSRLS）; 2) 启用 RLS + 策略."""
    # Step 1: 创建应用角色
    op.execute(f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nexus_app') THEN CREATE ROLE nexus_app LOGIN PASSWORD '{APP_DB_PASSWORD}' NOSUPERUSER NOBYPASSRLS; END IF; END $$;")

    # Step 2: 授权
    op.execute("GRANT CONNECT ON DATABASE nexus TO nexus_app")
    op.execute("GRANT USAGE ON SCHEMA public TO nexus_app")
    # 未来表的默认权限（用于 alembic 后续迁移自动建的表）
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nexus_app")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO nexus_app")
    # 已有表的权限
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nexus_app")
    op.execute("GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO nexus_app")

    # Step 3: 启用 RLS
    for table in MULTI_TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

        # CREATE POLICY：行 tenant_id = current GUC app.tenant_id 时可见
        # current_setting('app.tenant_id', TRUE) 第二个参数 TRUE 表示
        # GUC 不存在时返 NULL（用于 background job 无 tenant 场景）
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id::text = current_setting('app.tenant_id', TRUE))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', TRUE))
            """
        )


def downgrade() -> None:
    """关闭 RLS + 删除策略 + 移除 nexus_app 角色（仅回滚 RLS，不动表数据）."""
    for table in MULTI_TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # 不删除 nexus_app 角色（避免破坏运行中的应用连接）；只收回权限
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM nexus_app")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM nexus_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM nexus_app")
    op.execute("REVOKE CONNECT ON DATABASE nexus FROM nexus_app")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM nexus_app")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT, UPDATE ON SEQUENCES FROM nexus_app")


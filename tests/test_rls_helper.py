"""S1-3: PostgreSQL RLS helper unit tests.

测试 RLS 配套辅助逻辑（不连真实 Postgres，因为 RLS 真实效果需要
非 superuser 角色 + 完整 schema FK chain，单元测试层做不了）。

这里测试：
1. set_session_tenant_id() 正确写 / 清 session.info
2. get_db_with_tenant() 在 tenant_id=None 时不写 info
3. 在多租户表列表和 SQL 语法层面验证 RLS migration 正确
"""

import os
import re
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# set_session_tenant_id 行为
# ---------------------------------------------------------------------------


class TestSetSessionTenantId:
    """set_session_tenant_id() 写/清 session.info 的逻辑."""

    def test_set_writes_tenant_id(self):
        from nexus.db.database import set_session_tenant_id

        mock_session = type("S", (), {"info": {}})()
        set_session_tenant_id(mock_session, "tenant-aaa")
        assert mock_session.info["tenant_id"] == "tenant-aaa"

    def test_clear_removes_tenant_id(self):
        from nexus.db.database import set_session_tenant_id

        mock_session = type("S", (), {"info": {"tenant_id": "tenant-aaa"}})()
        set_session_tenant_id(mock_session, None)
        assert "tenant_id" not in mock_session.info

    def test_clear_when_no_tenant_id_is_noop(self):
        from nexus.db.database import set_session_tenant_id

        mock_session = type("S", (), {"info": {}})()
        # 不存在 tenant_id 时调用 clear 不应抛
        set_session_tenant_id(mock_session, None)
        assert "tenant_id" not in mock_session.info


# ---------------------------------------------------------------------------
# SQL 单引号转义（防 SQL 注入到 GUC SET）
# ---------------------------------------------------------------------------


class TestGucSqlInjection:
    """RLS GUC SET 必须防 SQL 注入."""

    def test_tenant_id_with_quote_does_not_break_sql(self):
        """含单引号的 tenant_id 不应导致 SQL 注入。"""
        from nexus.db.database import set_session_tenant_id

        mock_session = type("S", (), {"info": {}})()
        # 攻击者尝试注入：tenant'; DROP TABLE workflows; --
        malicious = "tenant-aaa'; DROP TABLE workflows; --"
        set_session_tenant_id(mock_session, malicious)

        # 验证：值被存进 info 字典（不做 SQL 解析）
        assert mock_session.info["tenant_id"] == malicious

        # 实际 SET 时的转义逻辑（看 db/database.py 源码）
        source = Path("nexus/db/database.py").read_text()
        # 必须有转义逻辑（用 replace('\\'', "\\\\'\\'") 或类似）
        assert "''" in source, (
            "database.py 应包含 SQL 单引号转义（用 '' 双单引号代替 '）"
        )


# ---------------------------------------------------------------------------
# RLS migration SQL 验证（静态分析）
# ---------------------------------------------------------------------------


class TestRLSMigrationStatic:
    """静态分析 add_row_level_security.py 确认 SQL 正确."""

    @pytest.fixture
    def migration_source(self):
        path = Path("nexus/db/migrations/versions/add_row_level_security.py")
        if not path.exists():
            pytest.skip("RLS migration not found")
        return path.read_text()

    def test_migration_creates_role(self, migration_source):
        """migration 必须 CREATE ROLE nexus_app."""
        assert "CREATE ROLE nexus_app" in migration_source
        # 必须 NOBYPASSRLS（否则 RLS 被旁路）
        assert "NOBYPASSRLS" in migration_source, (
            "应用角色必须 NOBYPASSRLS，否则 RLS 被 superuser 旁路机制绕过"
        )

    def test_migration_enables_rls_per_table(self, migration_source):
        """必须对每个 multi-tenant 表 ENABLE + FORCE ROW LEVEL SECURITY."""
        assert "ENABLE ROW LEVEL SECURITY" in migration_source
        assert "FORCE ROW LEVEL SECURITY" in migration_source, (
            "必须 FORCE，否则 table owner 角色会绕过 RLS"
        )

    def test_migration_creates_policy(self, migration_source):
        """必须 CREATE POLICY tenant_isolation 引用 current_setting GUC."""
        assert "CREATE POLICY" in migration_source
        assert "tenant_isolation" in migration_source
        # current_setting 第二个参数 TRUE = GUC 不存在返 NULL
        assert "current_setting('app.tenant_id', TRUE)" in migration_source, (
            "必须 current_setting(..., TRUE) 第二个参数为 TRUE，"
            "GUC 不存在时返 NULL（不抛错）"
        )

    def test_migration_uses_uuid_cast(self, migration_source):
        """tenant_id 列可能是 UUID 列，policy 必须 ::text 转换才匹配 GUC 字符串."""
        assert "tenant_id::text" in migration_source, (
            "policy 必须 ::text 把 UUID 强转成字符串与 GUC 字符串比较"
        )

    def test_migration_list_covers_all_models(self):
        """multi-tenant 表清单与 nexus/models/ 同步."""
        from nexus.db.migrations.versions.add_row_level_security import MULTI_TENANT_TABLES

        # 列出 models 中所有有 tenant_id 的表
        import ast
        model_tables = set()
        models_dir = Path("nexus/models")
        for f in models_dir.glob("*.py"):
            if f.name in ("__init__.py", "types.py"):
                continue
            content = f.read_text()
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for item in node.body:
                        if isinstance(item, ast.Assign):
                            for target in item.targets:
                                if isinstance(target, ast.Name) and target.id == "__tablename__":
                                    if isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
                                        # 查这个类是否有 tenant_id 字段
                                        for inner in node.body:
                                            if isinstance(inner, ast.AnnAssign) and isinstance(inner.target, ast.Name) and inner.target.id == "tenant_id":
                                                model_tables.add(item.value.value)
                                        break

        # 迁移清单必须是 model 表的超集（不含 tenants 自身）
        migration_tables = set(MULTI_TENANT_TABLES)
        missing_in_migration = model_tables - migration_tables - {"tenants"}
        assert not missing_in_migration, (
            f"以下 model 表有 tenant_id 但 RLS 迁移没覆盖: {missing_in_migration}"
        )


# ---------------------------------------------------------------------------
# 多租户表清单 sanity check
# ---------------------------------------------------------------------------


class TestMultiTenantTableList:
    """MULTI_TENANT_TABLES 列表本身的合理性."""

    def test_tenants_excluded(self):
        """tenants 表不应用 RLS（它是 parent，否则查 tenants 永远空集）."""
        from nexus.db.migrations.versions.add_row_level_security import MULTI_TENANT_TABLES
        assert "tenants" not in MULTI_TENANT_TABLES

    def test_includes_core_tables(self):
        """核心业务表必须包含."""
        from nexus.db.migrations.versions.add_row_level_security import MULTI_TENANT_TABLES
        required = ["workflows", "agents", "tools", "crews", "hitl_tasks", "api_keys"]
        for t in required:
            assert t in MULTI_TENANT_TABLES, f"{t} must be in MULTI_TENANT_TABLES"

    def test_list_is_alphabetized(self):
        """alphabetized 便于 code review 对比（误改易发现）."""
        from nexus.db.migrations.versions.add_row_level_security import MULTI_TENANT_TABLES
        assert MULTI_TENANT_TABLES == sorted(MULTI_TENANT_TABLES), (
            "MULTI_TENANT_TABLES 必须按字母序排列（code review 时易对比）"
        )

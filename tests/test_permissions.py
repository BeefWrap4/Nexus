"""权限系统测试 — RBAC 落地验证.

测试覆盖:
- PermissionEngine 角色权限矩阵
- ToolRegistry._check_permission 真实 RBAC 检查
- 便捷权限函数 (get_permissions_for_role, check_tool_permission)
"""

import pytest
from nexus.engine.permission_engine import Permission, PermissionEngine
from nexus.exceptions import PermissionDeniedException
from nexus.security.permissions import check_tool_permission, get_permissions_for_role
from nexus.tools.registry import Tool, ToolRegistry, ToolType


class TestPermissionEngine:
    """权限引擎 — 角色权限矩阵."""

    @pytest.fixture
    def engine(self) -> PermissionEngine:
        return PermissionEngine()

    def test_admin_has_all_permissions(self, engine: PermissionEngine):
        """Admin 拥有所有权限（包括 admin 本身）."""
        assert engine.has_permission("admin", Permission.WORKFLOW_READ)
        assert engine.has_permission("admin", Permission.WORKFLOW_WRITE)
        assert engine.has_permission("admin", Permission.WORKFLOW_EXECUTE)
        assert engine.has_permission("admin", Permission.WORKFLOW_DELETE)
        assert engine.has_permission("admin", Permission.AGENT_READ)
        assert engine.has_permission("admin", Permission.AGENT_EXECUTE)
        assert engine.has_permission("admin", Permission.TOOL_EXECUTE)
        assert engine.has_permission("admin", Permission.HITL_RESPOND)
        assert engine.has_permission("admin", "admin")

    def test_member_has_limited_permissions(self, engine: PermissionEngine):
        """Member 有读写执行权限，无删除和管理权限."""
        assert engine.has_permission("member", Permission.WORKFLOW_READ)
        assert engine.has_permission("member", Permission.WORKFLOW_WRITE)
        assert engine.has_permission("member", Permission.AGENT_EXECUTE)
        assert engine.has_permission("member", Permission.TOOL_EXECUTE)
        assert not engine.has_permission("member", Permission.AGENT_DELETE)
        assert not engine.has_permission("member", "admin")

    def test_viewer_read_only(self, engine: PermissionEngine):
        """Viewer 只有只读权限."""
        assert engine.has_permission("viewer", Permission.WORKFLOW_READ)
        assert engine.has_permission("viewer", Permission.AGENT_READ)
        assert engine.has_permission("viewer", Permission.TOOL_READ)
        assert engine.has_permission("viewer", Permission.RUN_READ)
        assert engine.has_permission("viewer", Permission.HITL_READ)
        assert not engine.has_permission("viewer", Permission.WORKFLOW_WRITE)
        assert not engine.has_permission("viewer", Permission.AGENT_EXECUTE)
        assert not engine.has_permission("viewer", Permission.TOOL_EXECUTE)
        assert not engine.has_permission("viewer", "admin")

    def test_unknown_role_no_permissions(self, engine: PermissionEngine):
        """未知角色没有任何权限."""
        assert not engine.has_permission("unknown", Permission.WORKFLOW_READ)
        assert not engine.has_permission("unknown", Permission.TOOL_EXECUTE)
        assert not engine.has_permission("unknown", "admin")

    def test_check_permission_raises_for_viewer_delete(self, engine: PermissionEngine):
        """viewer 删除工作流应抛出 PermissionDeniedException."""
        with pytest.raises(PermissionDeniedException):
            engine.check_permission("viewer", Permission.WORKFLOW_DELETE)

    def test_check_permission_passes_for_admin(self, engine: PermissionEngine):
        """admin 删除工作流不应报错."""
        engine.check_permission("admin", Permission.WORKFLOW_DELETE)

    def test_check_tenant_access_allows_same(self, engine: PermissionEngine):
        """同一租户允许访问."""
        engine.check_tenant_access("tenant1", "tenant1")

    def test_check_tenant_access_denies_different(self, engine: PermissionEngine):
        """不同租户拒绝访问."""
        with pytest.raises(PermissionDeniedException):
            engine.check_tenant_access("tenant1", "tenant2")

    def test_check_resource_access_owner_can_access(self, engine: PermissionEngine):
        """资源拥有者可以访问."""
        engine.check_resource_access(
            user_id="u1",
            user_role="member",
            resource_owner_id="u1",
            resource_tenant_id="t1",
            user_tenant_id="t1",
        )

    def test_check_resource_access_non_owner_denied(self, engine: PermissionEngine):
        """非 owner 的 member 不能访问他人资源."""
        with pytest.raises(PermissionDeniedException):
            engine.check_resource_access(
                user_id="u3",
                user_role="member",
                resource_owner_id="u1",
                resource_tenant_id="t1",
                user_tenant_id="t1",
            )

    def test_check_resource_access_admin_bypasses_owner(self, engine: PermissionEngine):
        """Admin 可以访问任意资源（绕过 owner 检查）."""
        engine.check_resource_access(
            user_id="u2",
            user_role="admin",
            resource_owner_id="u1",
            resource_tenant_id="t1",
            user_tenant_id="t1",
        )

    def test_filter_by_permission_admin_returns_all(self, engine: PermissionEngine):
        """Admin 过滤权限可看到所有 item."""
        items = [type("Item", (), {"created_by": "u1", "is_public": False})() for _ in range(3)]
        result = engine.filter_by_permission(items, "admin", "workflows:read")
        assert len(result) == 3

    def test_filter_by_permission_no_permission_returns_empty(self, engine: PermissionEngine):
        """无权限时返回空列表."""
        items = [type("Item", (), {"created_by": "u1", "is_public": False})() for _ in range(3)]
        result = engine.filter_by_permission(items, "viewer", "workflows:write")
        assert len(result) == 0

    def test_permission_enum_values(self):
        """验证 Permission 枚举值格式."""
        assert Permission.WORKFLOW_READ.value == "workflows:read"
        assert Permission.AGENT_EXECUTE.value == "agents:execute"
        assert Permission.TOOL_EXECUTE.value == "tools:execute"
        assert Permission.ADMIN.value == "admin"


class TestToolRegistryPermissions:
    """ToolRegistry._check_permission — 真实 RBAC 落地."""

    @pytest.fixture
    def registry(self) -> ToolRegistry:
        return ToolRegistry()

    @pytest.fixture
    def python_tool(self) -> Tool:
        return Tool(name="test_py", description="Python tool", type=ToolType.PYTHON)

    @pytest.fixture
    def http_tool(self) -> Tool:
        return Tool(name="test_http", description="HTTP tool", type=ToolType.HTTP)

    @pytest.fixture
    def sql_tool(self) -> Tool:
        return Tool(name="test_sql", description="SQL tool", type=ToolType.SQL)

    @pytest.fixture
    def mcp_tool(self) -> Tool:
        return Tool(name="test_mcp", description="MCP tool", type=ToolType.MCP)

    # --- Admin ---

    def test_admin_can_execute_python_tool(self, registry: ToolRegistry, python_tool: Tool):
        ctx = {"user_role": "admin", "user_id": "u1", "tenant_id": "t1"}
        assert registry._check_permission(ctx, python_tool) is True

    def test_admin_can_execute_http_tool(self, registry: ToolRegistry, http_tool: Tool):
        ctx = {"user_role": "admin", "user_id": "u1", "tenant_id": "t1"}
        assert registry._check_permission(ctx, http_tool) is True

    def test_admin_can_execute_all_tool_types(self, registry: ToolRegistry):
        for tool_type in ToolType:
            tool = Tool(name=f"t_{tool_type.value}", description="test", type=tool_type)
            ctx = {"user_role": "admin", "user_id": "u1", "tenant_id": "t1"}
            assert registry._check_permission(ctx, tool) is True

    # --- Member ---

    def test_member_can_execute_python_tool(self, registry: ToolRegistry, python_tool: Tool):
        ctx = {"user_role": "member", "user_id": "u1", "tenant_id": "t1"}
        assert registry._check_permission(ctx, python_tool) is True

    def test_member_can_execute_http_tool(self, registry: ToolRegistry, http_tool: Tool):
        ctx = {"user_role": "member", "user_id": "u1", "tenant_id": "t1"}
        assert registry._check_permission(ctx, http_tool) is True

    def test_member_can_execute_sql_tool(self, registry: ToolRegistry, sql_tool: Tool):
        ctx = {"user_role": "member", "user_id": "u1", "tenant_id": "t1"}
        assert registry._check_permission(ctx, sql_tool) is True

    def test_member_can_execute_mcp_tool(self, registry: ToolRegistry, mcp_tool: Tool):
        ctx = {"user_role": "member", "user_id": "u1", "tenant_id": "t1"}
        assert registry._check_permission(ctx, mcp_tool) is True

    # --- Viewer ---

    def test_viewer_cannot_execute_python_tool(self, registry: ToolRegistry, python_tool: Tool):
        ctx = {"user_role": "viewer", "user_id": "u1", "tenant_id": "t1"}
        assert registry._check_permission(ctx, python_tool) is False

    def test_viewer_cannot_execute_http_tool(self, registry: ToolRegistry, http_tool: Tool):
        ctx = {"user_role": "viewer", "user_id": "u1", "tenant_id": "t1"}
        assert registry._check_permission(ctx, http_tool) is False

    def test_viewer_cannot_execute_any_tool(self, registry: ToolRegistry):
        for tool_type in ToolType:
            tool = Tool(name=f"t_{tool_type.value}", description="test", type=tool_type)
            ctx = {"user_role": "viewer", "user_id": "u1", "tenant_id": "t1"}
            assert registry._check_permission(ctx, tool) is False

    # --- Unknown role ---

    def test_unknown_role_cannot_execute(self, registry: ToolRegistry, python_tool: Tool):
        ctx = {"user_role": "unknown", "user_id": "u1", "tenant_id": "t1"}
        assert registry._check_permission(ctx, python_tool) is False

    # --- Default role (member) ---

    def test_default_role_is_member(self, registry: ToolRegistry, python_tool: Tool):
        ctx = {"user_id": "u1", "tenant_id": "t1"}
        assert registry._check_permission(ctx, python_tool) is True

    # --- list_tools respects RBAC ---

    def test_list_tools_filters_by_permission(self, registry: ToolRegistry):
        registry.register(Tool(name="tool_a", description="A", type=ToolType.PYTHON))
        registry.register(Tool(name="tool_b", description="B", type=ToolType.HTTP))

        admin_ctx = {"user_role": "admin", "user_id": "u1", "tenant_id": "t1"}
        viewer_ctx = {"user_role": "viewer", "user_id": "u2", "tenant_id": "t1"}

        admin_tools = registry.list_tools(admin_ctx)
        viewer_tools = registry.list_tools(viewer_ctx)

        assert len(admin_tools) == 2
        assert len(viewer_tools) == 0

    # --- execute raises ToolPermissionDeniedException for viewer ---

    @pytest.mark.asyncio
    async def test_execute_raises_for_viewer(self, registry: ToolRegistry):
        from nexus.exceptions import ToolPermissionDeniedException

        registry.register(Tool(name="test_tool", description="test", type=ToolType.PYTHON))
        ctx = {"user_role": "viewer", "user_id": "u1", "tenant_id": "t1"}

        with pytest.raises(ToolPermissionDeniedException):
            await registry.execute("test_tool", {}, ctx)


class TestPermissionsModule:
    """nexus.security.permissions 便捷函数."""

    def test_get_permissions_for_admin(self):
        perms = get_permissions_for_role("admin")
        assert len(perms) > 10
        assert "admin" in perms
        assert "workflows:read" in perms
        assert "tools:execute" in perms

    def test_get_permissions_for_member(self):
        perms = get_permissions_for_role("member")
        assert "workflows:read" in perms
        assert "workflows:write" in perms
        assert "tools:execute" in perms
        assert "admin" not in perms
        assert "agents:delete" not in perms

    def test_get_permissions_for_viewer(self):
        perms = get_permissions_for_role("viewer")
        assert "workflows:read" in perms
        assert "workflows:write" not in perms
        assert "tools:execute" not in perms
        assert "admin" not in perms

    def test_get_permissions_for_unknown(self):
        perms = get_permissions_for_role("nonexistent")
        assert perms == []

    def test_check_tool_permission_admin(self):
        assert check_tool_permission("admin", "python") is True
        assert check_tool_permission("admin", "mcp") is True

    def test_check_tool_permission_member(self):
        assert check_tool_permission("member", "python") is True
        assert check_tool_permission("member", "http") is True

    def test_check_tool_permission_viewer(self):
        assert check_tool_permission("viewer", "python") is False
        assert check_tool_permission("viewer", "mcp") is False

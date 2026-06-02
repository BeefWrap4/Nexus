"""权限引擎 - 基于WAT InfoIsolation泛化.

WAT的InfoIsolation在事件层做信息隔离（visibility列表）。
NEXUS将其泛化为企业级权限系统:
- RBAC: 基于角色的访问控制
- 数据权限: 租户隔离 + 资源级权限
- 工具权限: 工具级访问控制
"""

from enum import Enum
from typing import Any

from nexus.exceptions import PermissionDeniedException


class Permission(str, Enum):
    """权限枚举."""

    # 工作流权限
    WORKFLOW_READ = "workflows:read"
    WORKFLOW_WRITE = "workflows:write"
    WORKFLOW_EXECUTE = "workflows:execute"
    WORKFLOW_DELETE = "workflows:delete"

    # Agent权限
    AGENT_READ = "agents:read"
    AGENT_WRITE = "agents:write"
    AGENT_EXECUTE = "agents:execute"
    AGENT_DELETE = "agents:delete"

    # 工具权限
    TOOL_READ = "tools:read"
    TOOL_WRITE = "tools:write"
    TOOL_EXECUTE = "tools:execute"
    TOOL_DELETE = "tools:delete"

    # 执行权限
    RUN_READ = "runs:read"
    RUN_EXECUTE = "runs:execute"
    RUN_CANCEL = "runs:cancel"

    # HITL权限
    HITL_READ = "hitl:read"
    HITL_RESPOND = "hitl:respond"

    # 管理权限
    ADMIN = "admin"


class PermissionEngine:
    """权限引擎."""

    # 角色到权限的映射
    ROLE_PERMISSIONS: dict[str, list[str]] = {
        "admin": [p.value for p in Permission],
        "member": [
            Permission.WORKFLOW_READ.value,
            Permission.WORKFLOW_WRITE.value,
            Permission.WORKFLOW_EXECUTE.value,
            Permission.AGENT_READ.value,
            Permission.AGENT_WRITE.value,
            Permission.AGENT_EXECUTE.value,
            Permission.TOOL_READ.value,
            Permission.TOOL_EXECUTE.value,
            Permission.RUN_READ.value,
            Permission.RUN_EXECUTE.value,
            Permission.HITL_READ.value,
            Permission.HITL_RESPOND.value,
        ],
        "viewer": [
            Permission.WORKFLOW_READ.value,
            Permission.AGENT_READ.value,
            Permission.TOOL_READ.value,
            Permission.RUN_READ.value,
            Permission.HITL_READ.value,
        ],
    }

    def has_permission(self, user_role: str, permission: str) -> bool:
        """检查角色是否有权限."""
        permissions = self.ROLE_PERMISSIONS.get(user_role, [])
        return permission in permissions or Permission.ADMIN.value in permissions

    def check_permission(self, user_role: str, permission: str) -> None:
        """检查权限，无权限则抛出异常."""
        if not self.has_permission(user_role, permission):
            raise PermissionDeniedException(action=permission)

    def filter_by_permission(
        self,
        items: list[Any],
        user_role: str,
        permission: str,
        owner_field: str = "created_by",
        user_id: str = "",
    ) -> list[Any]:
        """根据权限过滤列表."""
        if self.has_permission(user_role, Permission.ADMIN.value):
            return items
        if not self.has_permission(user_role, permission):
            return []
        return [
            item
            for item in items
            if getattr(item, owner_field, None) == user_id
            or getattr(item, "is_public", False)
        ]

    def check_tenant_access(self, user_tenant_id: str, resource_tenant_id: str) -> None:
        """检查租户访问权限."""
        if user_tenant_id != resource_tenant_id:
            raise PermissionDeniedException(
                resource=f"tenant:{resource_tenant_id}", action="access"
            )

    def check_resource_access(
        self,
        user_id: str,
        user_role: str,
        resource_owner_id: str,
        resource_tenant_id: str,
        user_tenant_id: str,
    ) -> None:
        """检查资源访问权限."""
        self.check_tenant_access(user_tenant_id, resource_tenant_id)
        if self.has_permission(user_role, Permission.ADMIN.value):
            return
        if resource_owner_id == user_id:
            return
        raise PermissionDeniedException()

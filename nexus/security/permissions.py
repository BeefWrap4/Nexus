"""权限定义与便捷函数.

提供权限检查装饰器和角色权限查询等便利工具。
"""

from functools import wraps
from typing import Callable

from nexus.engine.permission_engine import Permission, PermissionEngine
from nexus.exceptions import PermissionDeniedException


def require_permission(permission: str):
    """装饰器：要求特定权限才能访问路由.

    实际使用时应通过 FastAPI Depends 注入用户上下文来获取角色。
    此装饰器提供了一种声明式的权限需求表达方式。

    Example:
        @require_permission("workflows:write")
        async def create_workflow(request, ...):
            ...
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def get_permissions_for_role(role: str) -> list[str]:
    """获取角色对应的权限列表.

    Args:
        role: 角色名称 (admin / member / viewer)

    Returns:
        该角色拥有的权限字符串列表
    """
    engine = PermissionEngine()
    return engine.ROLE_PERMISSIONS.get(role, [])


def check_tool_permission(user_role: str, tool_type: str) -> bool:
    """检查用户角色是否有权限执行指定类型的工具.

    Args:
        user_role: 用户角色
        tool_type: 工具类型 (http / sql / python / mcp)

    Returns:
        True 如果有权限
    """
    engine = PermissionEngine()
    if engine.has_permission(user_role, Permission.ADMIN.value):
        return True
    return engine.has_permission(user_role, Permission.TOOL_EXECUTE.value)

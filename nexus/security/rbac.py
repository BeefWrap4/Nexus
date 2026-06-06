"""RBAC中间件.

基于角色的访问控制中间件。
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from nexus.engine.permission_engine import PermissionEngine
from nexus.exceptions import PermissionDeniedException


class RBACMiddleware(BaseHTTPMiddleware):
    """RBAC中间件.

    自动检查用户权限。
    """

    def __init__(self, app, permission_engine: PermissionEngine = None):
        super().__init__(app)
        self.permission_engine = permission_engine or PermissionEngine()

    async def dispatch(self, request: Request, call_next):
        """处理请求，接入 PermissionEngine 进行权限验证."""
        # 跳过公开端点
        PUBLIC_PATHS = {"/", "/health", "/docs", "/openapi.json", "/metrics"}
        if (request.url.path in PUBLIC_PATHS or 
            request.url.path.startswith("/docs/") or
            request.url.path.startswith("/api/v1/auth/")):  # Auth路由豁免认证
            return await call_next(request)

        # 获取用户信息
        user = getattr(request.state, "user", None)
        if not user:
            if request.headers.get("Authorization") or request.headers.get("X-API-Key"):
                return await call_next(request)
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required", "code": "UNAUTHORIZED"},
            )

        # 解析资源类型
        resource_type = self._parse_resource_type(request.url.path)
        if not resource_type:
            # 无法识别的路径，放行（由业务路由自行处理）
            return await call_next(request)

        # 解析操作
        action = self._parse_action(request.method)

        # 构建权限字符串并验证
        permission = f"{resource_type}:{action}"
        try:
            self.permission_engine.check_permission(user.role, permission)
        except PermissionDeniedException as e:
            return JSONResponse(
                status_code=403,
                content={"detail": str(e), "code": e.code},
            )

        return await call_next(request)

    @staticmethod
    def _parse_resource_type(path: str) -> str | None:
        """从请求路径解析资源类型."""
        parts = path.strip("/").split("/")
        KNOWN_RESOURCES = {
            "workflows", "agents", "tools", "crews", "runs", "hitl", "tenants",
            "prompts", "evals", "code-review", "traces", "mcp", "auto",
            "dashboard",
        }
        for part in parts:
            if part in KNOWN_RESOURCES:
                return part
        return None

    @staticmethod
    def _parse_action(method: str) -> str:
        """从 HTTP 方法解析操作."""
        action_map = {
            "GET": "read",
            "POST": "write",
            "PUT": "update",
            "PATCH": "update",
            "DELETE": "delete",
        }
        return action_map.get(method, "read")

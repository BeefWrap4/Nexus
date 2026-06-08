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
            request.url.path.startswith("/api/v1/auth/") or  # Auth路由豁免认证
            request.url.path.startswith("/api/v1/billing/webhook") or  # Stripe webhook uses signature verification
            request.url.path.startswith("/api/v1/webhooks/")):  # 修复 (P1 测试): webhook 用 HMAC 签名自验证, 不走 RBAC
            return await call_next(request)

        # 获取用户信息
        user = getattr(request.state, "user", None)
        if not user:
            # 修复 (P1, Phase 3.2 deny-by-default):
            # 旧逻辑: 有 auth header 就放行 (fail-open) 或无 auth header 返 401。
            # 两种路径都跳过权限检查 — 漏洞。新逻辑: 直接透传到路由,
            # 让 get_current_user 依赖决定 401 / 通过。这是 fail-CLOSED 的
            # 唯一安全行为 — 中间件绝不替依赖做"无凭据→放行"的判断。
            return await call_next(request)

        # 解析资源类型
        resource_type = self._parse_resource_type(request.url.path)
        if not resource_type:
            # 修复 (P1, Phase 3.2 deny-by-default):
            # 旧逻辑: 无法识别路径放行 (fail-open) — 任何不在 KNOWN_RESOURCES
            # 的路径都绕过权限检查。新逻辑: 拒绝 (403)。deny-by-default
            # 要求: 业务路由必须在 KNOWN_RESOURCES 中注册才可访问。
            return JSONResponse(
                status_code=403,
                content={
                    "detail": f"Unknown resource path: {request.url.path}",
                    "code": "FORBIDDEN",
                },
            )

        # 解析操作
        action = self._parse_action(request.method)

        # 构建权限字符串并验证
        permission = f"{resource_type}:{action}"
        # P0 fix (Task 1.5 second iteration): user 是 dict (从 get_current_user /
        # auth_context_middleware 来), 不是 User 对象。用 dict.get 而不是属性。
        try:
            user_role = user.get("role") if isinstance(user, dict) else getattr(user, "role", "member")
            self.permission_engine.check_permission(user_role, permission)
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

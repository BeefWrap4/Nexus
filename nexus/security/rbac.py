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
        """处理请求."""
        # 跳过公开端点
        if request.url.path in ["/health", "/docs", "/openapi.json"]:
            return await call_next(request)

        # 获取用户信息
        user = getattr(request.state, "user", None)
        if not user:
            return await call_next(request)

        # 检查权限（简化版）
        # 生产环境应根据路由和方法动态检查
        try:
            return await call_next(request)
        except PermissionDeniedException as e:
            return JSONResponse(
                status_code=403,
                content={"detail": str(e), "code": e.code},
            )

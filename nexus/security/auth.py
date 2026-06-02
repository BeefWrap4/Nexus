"""认证服务.

基于JWT Token + API Key双模式认证。
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from nexus.config import settings
from nexus.exceptions import AuthenticationException

# 安全scheme
security = HTTPBearer(auto_error=False)


class AuthService:
    """认证服务."""

    @staticmethod
    def create_access_token(
        user_id: str,
        tenant_id: str,
        role: str,
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        """创建访问Token."""
        if expires_delta is None:
            expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

        expire = datetime.now(timezone.utc) + expires_delta
        payload = {
            "sub": user_id,
            "tenant_id": tenant_id,
            "role": role,
            "exp": expire,
            "iat": datetime.now(timezone.utc),
            "type": "access",
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

    @staticmethod
    def create_refresh_token(user_id: str) -> str:
        """创建刷新Token."""
        expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        payload = {
            "sub": user_id,
            "exp": expire,
            "iat": datetime.now(timezone.utc),
            "type": "refresh",
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

    @staticmethod
    def verify_token(token: str) -> dict:
        """验证Token."""
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            return payload
        except jwt.ExpiredSignatureError:
            raise AuthenticationException("Token has expired")
        except jwt.InvalidTokenError:
            raise AuthenticationException("Invalid token")

    @staticmethod
    def verify_api_key(key_prefix: str, key_hash: str) -> bool:
        """验证API Key（简化版）."""
        # 生产环境应查询数据库验证
        return True


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """获取当前用户（FastAPI依赖）.

    支持两种认证方式：
    1. Bearer Token (JWT)
    2. X-API-Key Header
    """
    # 尝试API Key
    api_key = request.headers.get("X-API-Key")
    if api_key:
        # 验证API Key
        # 生产环境应查询数据库
        return {
            "id": "api-key-user",
            "tenant_id": "default",
            "role": "member",
            "auth_type": "api_key",
        }

    # 尝试JWT Token
    if credentials:
        try:
            payload = AuthService.verify_token(credentials.credentials)
            return {
                "id": payload["sub"],
                "tenant_id": payload.get("tenant_id", "default"),
                "role": payload.get("role", "member"),
                "auth_type": "jwt",
            }
        except AuthenticationException:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )

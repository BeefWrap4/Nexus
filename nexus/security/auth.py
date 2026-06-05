"""认证服务.

基于JWT Token + API Key双模式认证。

API Key 格式: nexus_<prefix>_<secret>
- prefix: 8位随机十六进制，用于数据库索引快速定位
- secret: 32位随机URL-safe字符串
- key_hash: HMAC-SHA256(SECRET_KEY, full_key)，存储于数据库
- 验证流程: 提取prefix → 数据库索引查询 → HMAC比对 → 过期/撤销检查
- 速率限制: 基于Redis滑动窗口算法，每个API Key独立计数
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.config import settings
from nexus.db.database import get_db
from nexus.exceptions import AuthenticationException
from nexus.models import APIKey, Tenant, User
from nexus.security.rate_limiter import RateLimiter

# 安全scheme
security = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# API Key 工具函数
# ---------------------------------------------------------------------------


def _hash_api_key(api_key: str) -> str:
    """使用 HMAC-SHA256 计算 API Key 的哈希.

    使用 SECRET_KEY 作为密钥，即使数据库泄露也无法伪造有效 API Key。
    """
    return hmac.new(
        settings.SECRET_KEY.encode(), api_key.encode(), hashlib.sha256
    ).hexdigest()


def _extract_key_prefix(api_key: str) -> str:
    """从 API Key 中提取前缀（用于数据库索引查询）.

    期望格式: nexus_<prefix>_<secret>
    返回 prefix 部分（最多20字符），不符合格式时返回前20字符。
    """
    parts = api_key.split("_")
    if len(parts) >= 2 and parts[0] == "nexus":
        return parts[1][:20]
    return api_key[:20]


async def _verify_api_key(db: AsyncSession, api_key: str) -> Optional[APIKey]:
    """验证 API Key（查询数据库）.

    验证流程:
    1. 提取 key_prefix，通过索引快速定位候选记录
    2. 计算 HMAC-SHA256 hash，与数据库中的 key_hash 精确比对
    3. 检查是否已过期（expires_at）
    4. 检查是否已撤销（revoked_at）
    5. 更新 last_used_at 时间戳

    Args:
        db: 数据库会话
        api_key: 客户端传入的原始 API Key

    Returns:
        验证通过的 APIKey 记录，或 None
    """
    key_hash = _hash_api_key(api_key)
    key_prefix = _extract_key_prefix(api_key)

    # 通过 prefix + hash 双重匹配，确保安全性
    stmt = (
        select(APIKey)
        .where(
            APIKey.key_prefix == key_prefix,
            APIKey.key_hash == key_hash,
            APIKey.revoked_at.is_(None),
        )
    )
    result = await db.execute(stmt)
    key_record = result.scalar_one_or_none()

    if not key_record:
        return None

    # 检查是否过期
    now = datetime.now(timezone.utc)
    if key_record.expires_at and key_record.expires_at.replace(tzinfo=timezone.utc) < now:
        return None

    # 更新最后使用时间（异步，不阻塞认证响应）
    key_record.last_used_at = now
    await db.commit()

    return key_record


# ---------------------------------------------------------------------------
# AuthService
# ---------------------------------------------------------------------------


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
    def generate_api_key(
        name: str = "Generated Key",
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        expires_days: Optional[int] = None,
    ) -> tuple[str, str, str]:
        """生成新的 API Key.

        Returns:
            (api_key, key_prefix, key_hash)
            - api_key: 原始 API Key（仅显示一次，需安全保存）
            - key_prefix: 前缀（用于索引）
            - key_hash: HMAC-SHA256 哈希（存储于数据库）
        """
        prefix = secrets.token_hex(4)  # 8位十六进制前缀
        secret = secrets.token_urlsafe(32)  # 32位随机字符串
        api_key = f"nexus_{prefix}_{secret}"

        key_prefix = prefix
        key_hash = _hash_api_key(api_key)

        return api_key, key_prefix, key_hash


# ---------------------------------------------------------------------------
# FastAPI 依赖
# ---------------------------------------------------------------------------


# JWT rate limiting — basic in-memory tracking (module-level persistence)
import time
_jwt_call_times: dict[str, list[float]] = {}


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """获取当前用户（FastAPI依赖）.

    支持两种认证方式：
    1. Bearer Token (JWT)
    2. X-API-Key Header（查数据库验证）

    Args:
        request: FastAPI 请求对象
        db: 数据库会话（FastAPI 自动注入）
        credentials: HTTP Bearer 凭证

    Returns:
        包含用户信息的 dict: {id, tenant_id, role, auth_type, permissions}

    Raises:
        HTTPException(401): 认证失败
        HTTPException(429): 超出速率限制
    """
    # ------------------------------------------------------------------
    # 方式1: API Key 认证
    # ------------------------------------------------------------------
    api_key = request.headers.get("X-API-Key")
    if api_key:
        # 开发环境回退：配置的 DEV_API_KEY 直接通过（方便测试/文档）
        if (
            settings.DEV_API_KEY
            and api_key == settings.DEV_API_KEY
            and settings.ENVIRONMENT == "development"
        ):
            tenant_id = str(UUID(int=0))
            result = await db.execute(select(Tenant).where(Tenant.slug == "default"))
            tenant = result.scalar_one_or_none()
            if tenant:
                tenant_id = str(tenant.id)

            return {
                "id": "dev-api-key-user",
                "tenant_id": tenant_id,
                "role": "admin",
                "auth_type": "api_key",
                "permissions": ["*"],
            }

        # 数据库验证
        key_record = await _verify_api_key(db, api_key)
        if key_record:
            # 速率限制检查（从 app.state 获取 Redis 客户端）
            redis_client = getattr(request.app.state, "redis", None)
            if redis_client:
                try:
                    limiter = RateLimiter(redis_client)
                    await limiter.check_rate_limit(
                        api_key=api_key,
                        limit=key_record.rate_limit or 1000,
                        window=key_record.rate_window or 60,
                    )
                except HTTPException as e:
                    if e.status_code == 429:
                        raise  # 重新抛出429错误
                    # 其他HTTP异常不阻断认证流程

            # 获取关联用户信息
            user = None
            if key_record.user_id:
                stmt = select(User).where(User.id == key_record.user_id)
                result = await db.execute(stmt)
                user = result.scalar_one_or_none()

            return {
                "id": str(user.id) if user else "api-key-user",
                "tenant_id": str(key_record.tenant_id),
                "role": user.role if user else "member",
                "auth_type": "api_key",
                "permissions": key_record.permissions or [],
            }

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ------------------------------------------------------------------
    # 方式2: JWT Token 认证
    # ------------------------------------------------------------------
    if credentials:
        try:
            payload = AuthService.verify_token(credentials.credentials)

            # JWT rate limiting — basic in-memory check (uses module-level _jwt_call_times)
            user_key = payload.get("sub", "unknown")
            now = time.time()
            if user_key not in _jwt_call_times:
                _jwt_call_times[user_key] = []
            _jwt_call_times[user_key] = [t for t in _jwt_call_times[user_key] if now - t < 60]
            _jwt_call_times[user_key].append(now)
            if len(_jwt_call_times[user_key]) > 200:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="JWT rate limit exceeded",
                )

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

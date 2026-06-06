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
import logging
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
# JWT 密钥管理
# ---------------------------------------------------------------------------


def get_jwt_signing_keys() -> list[str]:
    """获取JWT签名密钥列表.

    Returns:
        [当前密钥, 历史密钥1, 历史密钥2, ...]
        当前密钥用于签名，所有密钥都可用于验证。
    """
    keys = [settings.JWT_SECRET_KEY]
    if settings.JWT_PREVIOUS_SECRET_KEYS:
        keys.extend(settings.JWT_PREVIOUS_SECRET_KEYS)
    return keys


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
        """创建访问Token.

        使用JWT_SECRET_KEY进行签名，支持密钥轮换。
        """
        if expires_delta is None:
            expires_delta = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

        expire = datetime.now(timezone.utc) + expires_delta
        payload = {
            "sub": user_id,
            "tenant_id": tenant_id,
            "role": role,
            "exp": expire,
            "iat": datetime.now(timezone.utc),
            "type": "access",
        }
        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def create_refresh_token(user_id: str) -> str:
        """创建刷新Token.

        使用JWT_SECRET_KEY进行签名，支持密钥轮换。
        """
        expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
        payload = {
            "sub": user_id,
            "exp": expire,
            "iat": datetime.now(timezone.utc),
            "type": "refresh",
        }
        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def verify_token(token: str) -> dict:
        """验证Token.

        支持多密钥验证：先尝试当前密钥，失败后依次尝试历史密钥。
        这允许在密钥轮换期间，旧Token仍然有效直到过期。
        """
        signing_keys = get_jwt_signing_keys()
        last_error = None

        for key in signing_keys:
            try:
                payload = jwt.decode(token, key, algorithms=[settings.JWT_ALGORITHM])
                return payload
            except jwt.ExpiredSignatureError:
                # Token已过期，不再尝试其他密钥
                raise AuthenticationException("Token has expired")
            except jwt.InvalidTokenError as e:
                # 记录错误，继续尝试下一个密钥
                last_error = e
                continue

        # 所有密钥都验证失败
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
        # DEV_API_KEY 仅在开发环境用于快速测试,生产环境必须使用标准API Key流程
        if settings.DEV_API_KEY and settings.ENVIRONMENT == "development":
            # 开发环境允许使用DEV_API_KEY,但记录审计日志
            logger = logging.getLogger(__name__)
            logger.warning(
                f"DEV_API_KEY used for authentication. "
                f"This should NOT be used in production. IP: {request.client.host}"
            )
            if api_key == settings.DEV_API_KEY:
                tenant_id = str(UUID(int=0))
                result = await db.execute(select(Tenant).where(Tenant.slug == "default"))
                tenant = result.scalar_one_or_none()
                if tenant:
                    tenant_id = str(tenant.id)

                return {
                    "id": "dev-api-key-user",
                    "tenant_id": tenant_id,
                    "role": "admin",
                    "auth_type": "dev_api_key",  # 标记为开发密钥
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

            # JWT 速率限制：优先使用 Redis 滑动窗口（跨进程），fallback 到 in-memory dict
            user_key = payload.get("sub", "unknown")
            redis_client = getattr(request.app.state, "redis", None)
            if redis_client:
                try:
                    limiter = RateLimiter(redis_client)
                    await limiter.check_rate_limit(
                        api_key=f"jwt:{user_key}",
                        limit=200,
                        window=60,
                    )
                except HTTPException as e:
                    if e.status_code == 429:
                        raise  # 重新抛出 429
                    # 其他 Redis 异常不阻断认证（与 API Key 路径保持一致）
            else:
                # Fallback：进程内 in-memory 计数（单进程下足够）
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

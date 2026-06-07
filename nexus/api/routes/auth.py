"""认证API路由.

提供用户登录、注册、Token刷新等认证相关端点。
"""

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import get_db
from nexus.models import Tenant, User
from nexus.security.auth import AuthService, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


# ==================== Request Models ====================


class LoginRequest(BaseModel):
    """登录请求模型."""
    email: str
    password: str


class RefreshTokenRequest(BaseModel):
    """刷新Token请求模型."""
    refresh_token: str


class RegisterRequest(BaseModel):
    """注册请求模型."""
    email: str
    password: str
    name: Optional[str] = None
    tenant_slug: str = "default"


class SignupRequest(BaseModel):
    """Self-service signup request model.

    Unlike /register (which requires a pre-existing tenant), /signup creates
    both a Tenant and the requesting admin User in a single call. New
    customers can onboard in under 5 minutes.
    """
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    tenant_name: str = Field(min_length=2, max_length=255)
    name: str = Field(min_length=1, max_length=255)


@router.post("/login", summary="用户登录")
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """用户登录，验证邮箱和密码，返回JWT Token。

    Args:
        request: 登录请求（包含email和password）
        db: 数据库会话

    Returns:
        {
            "access_token": "eyJ...",
            "token_type": "bearer",
            "expires_in": 900,
            "user": {
                "id": "...",
                "email": "admin@nexus.local",
                "name": "System Administrator",
                "role": "admin",
                "tenant_id": "..."
            }
        }

    Raises:
        HTTPException(401): 邮箱或密码错误
        HTTPException(404): 用户不存在
    """
    # 查询用户（通过邮箱）
    stmt = select(User).where(User.email == request.email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        logger.warning(f"Login attempt for non-existent user: {request.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 验证密码
    if not user.password_hash:
        logger.warning(f"User {request.email} has no password hash set")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        password_valid = bcrypt.checkpw(
            request.password.encode("utf-8"),
            user.password_hash.encode("utf-8"),
        )
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication service error",
        )

    if not password_valid:
        logger.warning(f"Invalid password for user: {request.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 检查用户是否激活
    if not user.is_active:
        logger.warning(f"Login attempt for inactive user: {email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )

    # 更新最后登录时间
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    # 生成JWT Token
    access_token = AuthService.create_access_token(
        user_id=str(user.id),
        tenant_id=str(user.tenant_id),
        role=user.role,
    )
    refresh_token = AuthService.create_refresh_token(user_id=str(user.id))

    logger.info(f"User logged in successfully: {request.email} (id={user.id})")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 900,  # 15分钟
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "tenant_id": str(user.tenant_id),
            "avatar_url": user.avatar_url,
        },
    }


@router.get("/me", summary="获取当前用户信息")
async def get_current_user_info(
    current_user: dict = Depends(get_current_user),
):
    """获取当前登录用户的详细信息。

    需要有效的JWT Token或API Key。

    Returns:
        用户信息字典
    """
    return {
        "id": current_user["id"],
        "tenant_id": current_user["tenant_id"],
        "role": current_user["role"],
        "auth_type": current_user.get("auth_type", "jwt"),
    }


@router.post("/refresh", summary="刷新Access Token")
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """使用Refresh Token获取新的Access Token。

    Args:
        refresh_token: Refresh Token字符串
        db: 数据库会话

    Returns:
        {
            "access_token": "eyJ...",
            "token_type": "bearer",
            "expires_in": 900
        }

    Raises:
        HTTPException(401): Refresh Token无效或已过期
    """
    try:
        # 验证Refresh Token
        payload = AuthService.verify_token(request.refresh_token)

        # 检查Token类型
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 查询用户
        user_id = payload["sub"]
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 生成新的Access Token
        new_access_token = AuthService.create_access_token(
            user_id=str(user.id),
            tenant_id=str(user.tenant_id),
            role=user.role,
        )

        logger.info(f"Token refreshed for user: {user.email}")

        return {
            "access_token": new_access_token,
            "token_type": "bearer",
            "expires_in": 900,
        }

    except Exception as e:
        logger.error(f"Token refresh failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("/register", summary="用户注册（可选）")
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """注册新用户（如果系统允许自助注册）。

    Args:
        email: 用户邮箱
        password: 明文密码
        name: 用户姓名
        tenant_slug: 租户标识符（默认"default"）
        db: 数据库会话

    Returns:
        用户信息和JWT Token

    Raises:
        HTTPException(409): 邮箱已存在
        HTTPException(404): 租户不存在
    """
    # 检查邮箱是否已存在
    stmt = select(User).where(User.email == request.email)
    result = await db.execute(stmt)
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # 查询租户
    stmt = select(Tenant).where(Tenant.slug == request.tenant_slug)
    result = await db.execute(stmt)
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{request.tenant_slug}' not found",
        )

    # 生成密码哈希
    password_hash = bcrypt.hashpw(request.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    # 创建用户
    from uuid import uuid4

    new_user = User(
        id=uuid4(),
        tenant_id=tenant.id,
        email=request.email,
        name=request.name or request.email.split("@")[0],
        role="member",  # 默认角色
        password_hash=password_hash,
        is_active=True,
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    # 生成JWT Token
    access_token = AuthService.create_access_token(
        user_id=str(new_user.id),
        tenant_id=str(new_user.tenant_id),
        role=new_user.role,
    )

    logger.info(f"New user registered: {request.email} (id={new_user.id})")

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": str(new_user.id),
            "email": new_user.email,
            "name": new_user.name,
            "role": new_user.role,
            "tenant_id": str(new_user.tenant_id),
        },
    }


# ---------------------------------------------------------------------------
# Self-service signup — creates Tenant + admin User in one call
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    """Convert a tenant name to a URL-safe slug.

    Lowercase, replace non-alphanumeric runs with '-', trim, cap at 50 chars.
    Falls back to ``"tenant"`` when the name has no usable characters.
    """
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return s[:50] or "tenant"


@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    summary="自助注册（创建租户 + 管理员）",
)
async def signup(
    payload: SignupRequest,
    db: AsyncSession = Depends(get_db),
):
    """Self-service signup — creates a new tenant AND its first admin user
    in a single call. Returns a JWT so the customer lands in the dashboard
    without any operator hand-holding.

    Flow:
        1. Check email is not already taken (across all tenants).
        2. Create Tenant (plan=free trial, status=active).
        3. Hash the password with bcrypt.
        4. Create User with role=admin, is_active=True.
        5. Commit atomically; on slug collision append a short suffix.
        6. Issue access token (15 min) and return the user payload.

    Differs from ``/register``:
        - /register: requires pre-existing tenant_slug, role=member.
        - /signup:   creates tenant + admin, intended for new customers.

    Raises:
        HTTPException(409): Email already registered.
        HTTPException(409): Slug collision after retry (extremely rare).
    """
    email = payload.email.lower().strip()

    # 1. Check email not already taken
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # 2. Build a unique slug; retry once on collision
    base_slug = _slugify(payload.tenant_name)
    slug = base_slug
    for attempt in range(2):
        stmt = select(Tenant).where(Tenant.slug == slug)
        result = await db.execute(stmt)
        if result.scalar_one_or_none() is None:
            break
        slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Could not allocate a unique tenant slug for '{payload.tenant_name}'",
        )

    # 3. Create Tenant
    tenant = Tenant(
        id=uuid.uuid4(),
        name=payload.tenant_name,
        slug=slug,
        plan="free",  # default trial plan
        status="active",
        config={},
    )
    db.add(tenant)
    await db.flush()  # surface FK / constraint errors before User insert

    # 4. Hash password (bcrypt, same scheme as /register)
    password_hash = bcrypt.hashpw(
        payload.password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    # 5. Create admin user
    new_user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=email,
        name=payload.name,
        role="admin",
        password_hash=password_hash,
        is_active=True,
    )
    db.add(new_user)

    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Signup IntegrityError: {e}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    await db.refresh(new_user)
    await db.refresh(tenant)

    # 6. Issue JWT
    access_token = AuthService.create_access_token(
        user_id=str(new_user.id),
        tenant_id=str(tenant.id),
        role=new_user.role,
    )
    refresh_token = AuthService.create_refresh_token(user_id=str(new_user.id))

    logger.info(
        f"New tenant + admin created via /signup: "
        f"tenant_id={tenant.id}, user_id={new_user.id}, email={email}"
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 900,  # 15 minutes
        "user": {
            "id": str(new_user.id),
            "email": new_user.email,
            "name": new_user.name,
            "role": new_user.role,
            "tenant_id": str(tenant.id),
        },
    }

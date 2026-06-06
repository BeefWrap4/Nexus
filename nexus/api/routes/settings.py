"""Settings + API Key 管理 API.

修复 (前端): Settings.vue 调 GET /settings + /api-keys + POST /settings/* + /api-keys
/api-keys 路由**真正写入数据库** (api_keys 表, RLS by tenant) — 之前的 stub
返回假 key, 不能用于程序化访问。

api_keys 表 schema (initial_migration.py):
  id, tenant_id, user_id, name, key_hash, key_prefix,
  permissions (JSON), rate_limit, rate_window,
  last_used_at, expires_at, created_at, revoked_at
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import get_tenant_db
from nexus.models import APIKey
from nexus.security.auth import AuthService, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────── Settings ───────────────────

@router.get("")
async def get_all_settings(
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """拉所有设置 (3 类: general / llm / security).

    修复 (前端): Settings.vue 默认 GET /settings, 之前 404, 现在返回
    默认值结构, 前端能渲染表单。
    """
    return {
        "general": {
            "app_name": "NEXUS",
            "app_version": "0.1.0",
            "default_language": "zh-CN",
            "theme": "light",
        },
        "llm": {
            "default_model": "deepseek-chat",
            "default_temperature": 0.2,
            "default_max_tokens": 2000,
        },
        "security": {
            "rate_limit_per_minute": 1000,
            "require_mfa": False,
            "session_timeout_minutes": 60,
        },
    }


@router.post("/general")
async def save_general_settings(
    values: dict[str, Any],
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """保存通用设置 — 当前 stub, 仅记日志."""
    logger.info("save_general_settings user=%s values=%s", current_user.get("id"), values)
    return {"ok": True, "saved": values}


@router.post("/llm")
async def save_llm_settings(
    values: dict[str, Any],
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """保存 LLM 默认设置 — stub."""
    logger.info("save_llm_settings user=%s values=%s", current_user.get("id"), values)
    return {"ok": True, "saved": values}


@router.post("/security")
async def save_security_settings(
    values: dict[str, Any],
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """保存安全设置 — stub."""
    logger.info("save_security_settings user=%s values=%s", current_user.get("id"), values)
    return {"ok": True, "saved": values}


# ─────────────────── API Keys (真写库) ───────────────────

# 修复: Settings.vue 调用 /api-keys (顶层), 不用 /settings/api-keys。
# 这里走独立 router (prefix='/api/v1') 暴露三个端点。
api_keys_router = APIRouter()


def _serialize_key(row: APIKey, raw_key: str | None = None) -> dict:
    """DB row → 前端 dict. raw_key 仅在创建时传 (用户保存 key 唯一机会)."""
    return {
        "id": str(row.id),
        "name": row.name,
        "key_prefix": row.key_prefix,
        # 前端 Settings.vue 期望字段 (看代码):
        "prefix": row.key_prefix,
        "permissions": row.permissions or [],
        "rate_limit": row.rate_limit,
        "rate_window": row.rate_window,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        # raw key 只在创建时返回
        "key": raw_key,
    }


@api_keys_router.get("/api-keys")
async def list_api_keys(
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """列当前 tenant 的 API Keys (按创建时间倒序, 不含已撤销的)."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="用户无 tenant_id")
    result = await db.execute(
        select(APIKey)
        .where(APIKey.tenant_id == UUID(tenant_id))
        .where(APIKey.revoked_at.is_(None))
        .order_by(APIKey.created_at.desc())
    )
    return [_serialize_key(row) for row in result.scalars().all()]


@api_keys_router.post("/api-keys")
async def create_api_key(
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """创建 API Key — 真正生成随机 key, 存 hash, 一次性返回明文.

    Returns:
        包含完整 api_key (明文, **只这一次能看到**) + 数据库字段
    """
    tenant_id = current_user.get("tenant_id")
    user_id = current_user.get("id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="用户无 tenant_id")

    name = (payload.get("name") or "unnamed").strip()[:255]
    permissions = payload.get("permissions") or []
    rate_limit = int(payload.get("rate_limit") or 1000)
    expires_days = payload.get("expires_days")

    # 用现有 AuthService.generate_api_key 生成 (api_key, prefix, hash)
    api_key, key_prefix, key_hash = AuthService.generate_api_key(
        name=name,
        tenant_id=tenant_id,
        user_id=user_id,
        expires_days=expires_days,
    )

    from datetime import datetime, timedelta, timezone
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=expires_days)
        if expires_days else None
    )

    row = APIKey(
        tenant_id=UUID(tenant_id),
        user_id=UUID(user_id) if user_id else None,
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        permissions=permissions,
        rate_limit=rate_limit,
        rate_window=60,
        expires_at=expires_at,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    logger.info(
        "api_key_created tenant=%s user=%s name=%s prefix=%s",
        tenant_id, user_id, name, key_prefix,
    )
    # 明文 key 只此一次返回
    return _serialize_key(row, raw_key=api_key)


@api_keys_router.delete("/api-keys/{key_id}")
async def delete_api_key(
    key_id: str,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """软删 (revoke) — 保留审计行, 后续 _verify_api_key 会拒."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="用户无 tenant_id")
    try:
        key_uuid = UUID(key_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="key_id 必须是 UUID")

    result = await db.execute(
        select(APIKey)
        .where(APIKey.id == key_uuid)
        .where(APIKey.tenant_id == UUID(tenant_id))
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="API key not found")

    from datetime import datetime, timezone
    row.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("api_key_revoked tenant=%s key_id=%s", tenant_id, key_id)
    return {"ok": True, "revoked": key_id}

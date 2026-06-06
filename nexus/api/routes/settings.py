"""Settings + API Key 管理 API.

修复 (前端): Settings.vue 调 GET /settings + /api-keys + POST /settings/* + /api-keys
但后端没有这俩 router。补上最小可用实现 — 当前都返回空 / 默认值, 等真的需要
持久化再扩。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import get_tenant_db
from nexus.security.auth import get_current_user

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


# ─────────────────── API Keys ───────────────────

# 修复: Settings.vue 调用 /api-keys (顶层), 不用 /settings/api-keys。
# 这里走独立 router (prefix='/api/v1') 暴露两个端点。
api_keys_router = APIRouter()


@api_keys_router.get("/api-keys")
async def list_api_keys(
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """列当前用户的 API Keys — stub 返回空数组."""
    return []


@api_keys_router.post("/api-keys")
async def create_api_key(
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """创建 API Key — stub, 真要落地需要写 api_keys 表."""
    name = payload.get("name", "unnamed")
    return {
        "id": "stub-key-id",
        "name": name,
        "key": "nexus_stub_" + "x" * 32,
        "prefix": "stub",
        "created_at": "2026-06-06T00:00:00Z",
        "warning": "STUB — 真实 API Key 创建还没实现",
    }


@api_keys_router.delete("/api-keys/{key_id}")
async def delete_api_key(
    key_id: str,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """删 API Key — stub."""
    logger.info("delete_api_key user=%s key_id=%s", current_user.get("id"), key_id)
    return {"ok": True, "deleted": key_id}

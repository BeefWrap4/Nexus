"""Runtime config helpers (P0 fix for Task 1.5).

P0 修复: review 发现 Settings.vue 的 piiEnabled / auditEnabled switches
"看上去能改", 但实际行为从来不变 — 因为:

  - audit_middleware 读 ``settings.AUDIT_ENABLED`` (env var, 启动时锁)
  - LLMClient 的 ``_pii_guard`` 在模块导入时根据 ``settings.PII_ENABLED``
    一次性决定, 之后永不重新评估

前端 POST /api/v1/settings/security 把值存到 system_settings 表 —
值确实落库了, 但所有运行时都读 env var, 不读 system_settings。

修法: 引入带缓存的 SystemSetting 查表函数, 让 audit_middleware / 未来的
PII runtime toggle 都用它。30 秒 cache, 避免每个请求都查 DB。

Fallback: 如果 SystemSetting 表里**没**这条记录, 退回 env var。这样:

  - 第一次部署: 行为跟 env var 一样 (向后兼容)
  - 后续: 前端开关改 DB → 30 秒内所有 audit 行为跟着变
  - 系统设置缺失: 不破不立, 继续按 env var 走
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 进程内 cache — (value, ts) 元组
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[Any, float]] = {}
_CACHE_TTL_SECONDS: float = 30.0
_cache_lock = asyncio.Lock()


def _cache_get(key: str) -> Optional[Any]:
    """同步 cache lookup — 过期返 None (调用方会查 DB)."""
    entry = _cache.get(key)
    if entry is None:
        return None
    value, ts = entry
    if time.time() - ts >= _CACHE_TTL_SECONDS:
        return None
    return value


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (value, time.time())


def invalidate_cache() -> None:
    """手动清空 cache — settings API 在写入后可调, 立即生效."""
    _cache.clear()


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


async def _lookup_setting(
    tenant_id: str,
    key: str,
    category: str,
    fallback_env_attr: str,
) -> bool:
    """查 SystemSetting (带 cache), 缺失时退回 settings.<env_attr>.

    Args:
        tenant_id: 租户 ID (None 时直接走 env fallback, 不会查到 DB)
        key: SystemSetting.key
        category: SystemSetting.category
        fallback_env_attr: Settings 中对应的 env-bound 属性名 (如 'PII_ENABLED')

    Returns:
        bool — 该项是否"启用"
    """
    if not tenant_id:
        return _env_fallback(fallback_env_attr)

    cache_key = f"{category}:{key}:{tenant_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return bool(cached)

    # 查 DB — 用独立的 session, 不污染请求 session
    try:
        from sqlalchemy import select

        from nexus.db.database import AsyncSessionLocal
        from nexus.models import SystemSetting

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(SystemSetting)
                .where(SystemSetting.tenant_id == tenant_id)
                .where(SystemSetting.key == key)
                .where(SystemSetting.category == category)
            )
            row = result.scalar_one_or_none()
            if row is None:
                value = _env_fallback(fallback_env_attr)
            else:
                value = bool(row.value)
    except Exception as exc:  # noqa: BLE001
        # DB 挂了 / 表不存在 / migration 没跑 — 退到 env var, 记 warning
        logger.warning(
            "runtime_config_lookup_failed key=%s tenant=%s err=%s — using env fallback",
            key, tenant_id, exc,
        )
        value = _env_fallback(fallback_env_attr)

    _cache_set(cache_key, value)
    return value


def _env_fallback(attr: str) -> bool:
    """读 settings.<attr> (env-bound), 异常时返 True (fail-secure 关闭)."""
    try:
        from nexus.config import settings
        return bool(getattr(settings, attr, True))
    except Exception:  # noqa: BLE001
        return True


async def is_audit_enabled(tenant_id: Optional[str]) -> bool:
    """Tenant 维度的 audit_middleware 开关.

    调用方: audit_log_middleware.

    Returns:
        True — 写 audit_logs; False — pass-through.
    """
    return await _lookup_setting(
        tenant_id=tenant_id or "",
        key="auditEnabled",
        category="security",
        fallback_env_attr="AUDIT_ENABLED",
    )


async def is_pii_enabled(tenant_id: Optional[str]) -> bool:
    """Tenant 维度的 PII 脱敏开关.

    调用方: agent/llm_client.py (LlmClient 内部 sanitize helpers).

    Returns:
        True — 脱敏; False — 原样透传.
    """
    return await _lookup_setting(
        tenant_id=tenant_id or "",
        key="piiEnabled",
        category="security",
        fallback_env_attr="PII_ENABLED",
    )

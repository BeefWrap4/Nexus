"""审计日志中间件 (P0 Task 1.5).

每个 mutating API 请求 (POST/PUT/PATCH/DELETE) 在响应成功后写入一行 audit_logs。
公开端点、5xx 响应、未认证请求会被跳过 — 避免噪声 / 暴露错误。

设计要点:
- 失败-软 (fail-soft): 写日志抛异常不会让请求 5xx，仅记 warning。
- 默认开启: settings.AUDIT_ENABLED=True 触发，关闭后中间件直接 pass-through。
- 异步安全: 用独立 session (`get_db()` 上下文管理器) 写日志，避免污染请求的
  session 状态（不持有事务、不持租户上下文）。
- 性能: 仅在 mutating 方法上做轻量级 parse + insert，无额外 I/O 依赖。

公开端点 (RBAC 也豁免): /, /health, /docs, /openapi.json, /metrics, /api/v1/auth/*。
未认证请求: RBAC 中间件会先 401，审计只关心通过鉴权的真实操作。
"""

import logging
from typing import Optional

from fastapi import Request
from starlette.responses import Response

from nexus.config import settings
# 模块级导入，方便测试 monkeypatch（不要延迟到函数内）
from nexus.db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


# 公开端点 — 不写审计（与 RBAC 一致）
_PUBLIC_EXACT = {"/", "/health", "/docs", "/openapi.json", "/metrics"}
_PUBLIC_PREFIXES = (
    "/api/v1/auth/",
    "/api/v1/webhooks/",
)
# HTTP method -> action 映射（与 RBAC 保持一致）
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _is_public(path: str) -> bool:
    """公开端点判断（不写审计日志）."""
    if path in _PUBLIC_EXACT:
        return True
    return any(path.startswith(p) for p in _PUBLIC_PREFIXES)


def _parse_resource_type(path: str) -> str:
    """从 path 提取 resource type: /api/v1/workflows/abc → workflows.

    Fallback: 取第一段非 api/v1 的 segment。
    """
    parts = [p for p in path.split("/") if p and p not in ("api", "v1")]
    if not parts:
        return "unknown"
    return parts[0]


def _parse_resource_id(path: str) -> Optional[str]:
    """从 path 提取 resource id: /api/v1/workflows/abc/edit → abc.

    取第一个看起来像 UUID / 短字符串 token 的 segment。
    """
    parts = [p for p in path.split("/") if p and p not in ("api", "v1")]
    if len(parts) < 2:
        return None
    # 跳过纯动作词 (run / versions / clone / schedule / etc.)
    _ACTION_WORDS = {"run", "runs", "versions", "clone", "schedule", "stats", "ask"}
    if parts[1] in _ACTION_WORDS:
        return None
    candidate = parts[1]
    # 必须是合法 ID 形状 — 至少 8 字符，alnum + dash
    if len(candidate) < 8 or not all(c.isalnum() or c == "-" for c in candidate):
        return None
    return candidate


async def audit_log_middleware(request: Request, call_next) -> Response:
    """审计日志中间件主体.

    仅 mutating + 已认证 + 非公开 + 非 5xx 的请求会写 audit_logs。
    """
    if not settings.AUDIT_ENABLED:
        return await call_next(request)

    # 非 mutating 方法直接 pass-through（GET/HEAD/OPTIONS）
    if request.method not in _MUTATING_METHODS:
        return await call_next(request)

    # 公开端点不写审计
    if _is_public(request.url.path):
        return await call_next(request)

    # 先放行请求拿到响应
    response = await call_next(request)

    # 5xx 跳过（应有专门告警链路，不归审计）
    if response.status_code >= 500:
        return response

    # 未认证请求跳过（RBAC 已 401，user 为空）
    user = getattr(request.state, "user", None)
    if not user:
        return response

    # 写 audit_logs（失败软处理 — 任何异常都仅记 warning，不影响响应）
    try:
        from nexus.models.audit import AuditLog
        from uuid import UUID

        # 解析 user/tenant id
        user_id_raw = user.get("id")
        tenant_id_raw = user.get("tenant_id")
        user_id: Optional[UUID] = None
        tenant_id: Optional[UUID] = None
        try:
            if user_id_raw and str(user_id_raw).strip():
                user_id = UUID(str(user_id_raw))
        except (ValueError, TypeError):
            user_id = None
        try:
            if tenant_id_raw and str(tenant_id_raw).strip():
                tenant_id = UUID(str(tenant_id_raw))
        except (ValueError, TypeError):
            tenant_id = None

        # 缺 tenant_id 不写（无法 enforce RLS / 多租户隔离）
        if tenant_id is None:
            return response

        resource_id_str = _parse_resource_id(request.url.path)
        resource_id: UUID
        try:
            resource_id = UUID(resource_id_str) if resource_id_str else UUID(int=0)
        except (ValueError, TypeError):
            # 非 UUID resource id — 用占位 UUID（保留 type 与 action 记录）
            resource_id = UUID(int=0)

        async with AsyncSessionLocal() as session:
            session.add(
                AuditLog(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    action=request.method,
                    resource_type=_parse_resource_type(request.url.path),
                    resource_id=resource_id,
                    ip_address=(request.client.host if request.client else None),
                    user_agent=request.headers.get("user-agent"),
                    payload={"path": request.url.path, "status": response.status_code},
                )
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "audit_log_write_failed path=%s method=%s err=%s",
            request.url.path,
            request.method,
            exc,
        )

    return response

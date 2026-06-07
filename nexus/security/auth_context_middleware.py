"""Auth context 中间件 (P0 fix for Task 1.5).

P0 修复: review 发现 audit_middleware / RBAC / get_tenant_db 都读
``request.state.user``, 但代码里**没有任何地方**写入这个属性 —
``get_current_user`` 是个 FastAPI 依赖, 只返 dict, 不 mutate request.state。

结果:
- audit_middleware 看到的 user 永远是 None → 一次 audit row 都不写。
- RBAC middleware 看到的 user 永远是 None → 401, 然后 audit 跳过,
  死循环。
- get_tenant_db 看到的 user 永远是 None → RLS GUC 永不注入,
  RLS 变成 theater。

这个中间件是 *best-effort* 的修复: 用 STarlette ``BaseHTTPMiddleware`` /
裸 middleware 函数, 在 auth chain 之前先把 Authorization / X-API-Key 解析
到 ``request.state.user``。它**不会**抛 401 — 真正的 401 由
``get_current_user`` 依赖在 endpoint 调用时抛 (它有 DB 访问权)。

注册顺序 (main.py):
- 这是个普通 ``@app.middleware("http")`` 装饰的函数, 注册到 app 上
  后会成为整个 stack 的**最内层** (靠近 endpoint) — 也就是说它在
  audit_middleware 之后才跑。但 audit_middleware 也是 ``@app.middleware("http")``,
  后注册的内层, 先注册的在外层。所以:

    注册顺序: auth_context (先) → audit (后)
    实际运行顺序: audit (外层) → auth_context (内层)

  这**不**是我们想要的。我们想要 auth_context 跑在最外层 (在 audit 之前
  设置好 user, 让 audit 看得到)。

修复方式: 在 main.py 里把 auth_context 装饰**最后**注册, 这样它在外层
运行 (Starlette 的 middleware 栈是反向入栈)。本文件不直接 import main.py,
调用方按注释的顺序注册。

策略:
- Authorization: Bearer <jwt>    → jwt.decode 不查 DB
- X-API-Key: nexus_* / dev-*    → 只标记 "API key 头在", 不查 DB
                                  (真正的验证由 get_current_user 完成,
                                  它可以查 DB 拿到完整租户信息)

任何异常都被 catch — 这是 best-effort, 不允许中断请求链。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


def _decode_jwt_no_db(token: str) -> Optional[dict[str, Any]]:
    """JWT 解码 (无 DB 查). 失败返 None.

    用 nexus.security.auth.AuthService.verify_token — 它支持多密钥轮换,
    与 get_current_user 用的是同一套, 保证一致。
    """
    try:
        # 局部 import 避免循环 (audit_middleware 启动时 import chain 安全)
        from nexus.security.auth import AuthService

        # verify_token 在 token 过期/无效时抛 AuthenticationException
        return AuthService.verify_token(token)
    except Exception:  # noqa: BLE001
        return None


def _looks_like_api_key(key: str) -> bool:
    """快速 format check — 不查 DB.

    完整验证 (HMAC 比对 / 过期 / 撤销) 由 get_current_user 完成。
    """
    if not key:
        return False
    # nexus_<prefix>_<secret> 形式
    if key.startswith("nexus_") and key.count("_") >= 2:
        return True
    # dev-* 是 development 环境的 DEV_API_KEY 形式
    if key.startswith("dev-"):
        return True
    return False


async def auth_context_middleware(request: Request, call_next) -> Response:
    """Auth context middleware 主体.

    把 Authorization (JWT) / X-API-Key 解码结果写到 request.state.user,
    让下游的 RBAC / audit / get_tenant_db 都能看到。

    任何异常都被 catch — 不允许中间件本身让请求失败。
    """
    # 默认 — 未认证
    try:
        request.state.user = None  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        # request.state 在极早期可能没初始化, 保险起见 try 一下
        pass

    try:
        # 方式 1: JWT (Bearer)
        auth = request.headers.get("Authorization") or request.headers.get("authorization")
        if auth and auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if token:
                payload = _decode_jwt_no_db(token)
                if payload:
                    # 写成依赖同款 dict shape, 让 audit/RBAC 不需要改
                    user: dict[str, Any] = {
                        "id": payload.get("sub"),
                        "tenant_id": payload.get("tenant_id"),
                        "role": payload.get("role", "member"),
                        "auth_type": "jwt",
                        "permissions": [],
                    }
                    try:
                        request.state.user = user  # type: ignore[attr-defined]
                    except Exception:  # noqa: BLE001
                        pass
                    return await call_next(request)

        # 方式 2: X-API-Key
        api_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
        if api_key and _looks_like_api_key(api_key):
            # 不查 DB — 真实验证在 get_current_user 依赖里完成。
            # 这里只标记 "API key 头在", 防止审计被错误跳过。
            # tenant_id 留 None, audit_middleware 会因为 tenant_id 缺失跳过,
            # 这是正确的: 真正有 tenant_id 的 audit row 由 get_current_user
            # 之后, RBAC 通过后才写。
            try:
                request.state.user = {  # type: ignore[attr-defined]
                    "id": None,
                    "tenant_id": None,
                    "role": "member",
                    "auth_type": "api_key",
                    "permissions": [],
                    "api_key_present": True,
                }
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        # 不允许 middleware 异常阻断请求 — 记 warning 即可
        logger.warning("auth_context_middleware_error err=%s", exc)

    return await call_next(request)

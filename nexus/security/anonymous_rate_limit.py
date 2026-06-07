"""Pre-auth rate limit middleware.

Runs BEFORE get_current_user. Key is client IP (X-Forwarded-For first
hop, falling back to request.client.host). Limit is per-IP sliding
window.

Public paths (/, /health, /metrics) ARE rate-limited — the security
reviewer flagged these as floodable in a DoS scenario (an attacker
hitting /health in a tight loop can keep the event loop busy serving
200 OK responses with no auth check at all).

Failure mode: if Redis is unreachable, this middleware FAILS OPEN
(allow + log a warning) so a Redis outage does not turn into a full
API outage. The per-IP auth/RBAC rate limiters inside get_current_user
provide a second layer of defense for authenticated traffic.
"""
import logging
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from nexus.config import settings
from nexus.security.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


def _get_rate_limiter() -> Optional[RateLimiter]:
    """Lazily build a RateLimiter from the app's redis client.

    The redis client is attached to app.state.redis during the FastAPI
    lifespan. The middleware runs inside a request, so the app is
    already up by the time we are called. We return None if redis is
    missing — the caller treats None as "fail open".
    """
    # Imported lazily so this module is importable before app.state
    # exists (e.g. during unit-test module collection).
    from nexus.api.main import app  # noqa: PLC0415

    redis_client = getattr(app.state, "redis", None)
    if redis_client is None:
        return None
    return RateLimiter(redis_client)


async def anonymous_rate_limit_middleware(request: Request, call_next) -> Response:
    """Reject requests that exceed the per-IP anonymous rate limit."""
    if not settings.ANONYMOUS_RATE_LIMIT_ENABLED:
        return await call_next(request)

    limiter = _get_rate_limiter()
    if limiter is None:
        # No redis client — fail open.
        return await call_next(request)

    client_ip = _get_client_ip(request)
    key = f"anon:{client_ip}"

    # RateLimiter.check_rate_limit raises HTTPException(429) when the
    # caller is over the limit (it does not return allowed=False). We
    # catch that specific status and convert it to a JSONResponse so
    # the limit triggers 429 *before* auth runs. We do NOT want to
    # fail open on a 429 — that would defeat the whole point of the
    # middleware. Network / Redis errors raise OTHER exception types
    # (ConnectionError, TimeoutError, RedisError) — those are the ones
    # we want to fail open on.
    try:
        await limiter.check_rate_limit(
            api_key=key,
            limit=settings.ANONYMOUS_RATE_LIMIT_PER_MINUTE,
            window=60,
        )
    except HTTPException as exc:
        if exc.status_code == 429:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
                headers={"Retry-After": "60"},
            )
        # Non-429 HTTPException from RateLimiter would be unusual,
        # but propagate it untouched rather than fail open.
        raise
    except Exception as exc:  # noqa: BLE001
        # Fail open: redis down / timeout / serialization — do not 500
        # the whole API just because rate-limit storage is unreachable.
        logger.warning(
            "anonymous_rate_limit_check_failed ip=%s err=%s",
            client_ip,
            exc,
        )
        return await call_next(request)

    return await call_next(request)


def _get_client_ip(request: Request) -> str:
    """Extract client IP, preferring X-Forwarded-For (first hop)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # First entry is the original client; the rest are proxies.
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"

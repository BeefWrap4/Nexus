"""FastAPI主应用.

基于WAT api/app.py 升级:
- 复用FastAPI结构
- 扩展为多租户API
- 增加MCP Gateway支持
- 集成OpenTelemetry
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.exc import SQLAlchemyError

from nexus.config import settings
from nexus.db.database import close_db, init_db
from nexus.engine.event_bus import EventBus
from nexus.exceptions import NexusException
from nexus.jobs.pool import close_arq_pool, init_arq_pool
from nexus.security.rbac import RBACMiddleware


def _validate_production_security() -> None:
    """生产环境启动前安全校验.

    确保关键安全配置已正确设置，防止使用默认值部署到生产环境。
    
    校验项:
    1. SECRET_KEY 强度检查（禁止使用默认值，长度≥32字符）
    2. 数据库 URL 检查（禁止使用 SQLite）
    3. DEV_API_KEY 检查（生产环境禁止设置）
    4. CORS 配置检查（生产环境禁止使用通配符 *）
    5. DEBUG 模式检查（生产环境必须关闭）
    6. Redis 连接检查（生产环境必须配置）
    """
    import logging

    logger = logging.getLogger(__name__)

    # SECRET_KEY 校验
    dev_secrets = {
        "nexus-dev-secret-not-for-production",
        "change-me-in-production",
        "your-secret-key-change-in-production",
    }
    if settings.SECRET_KEY in dev_secrets or len(settings.SECRET_KEY) < 32:
        raise RuntimeError(
            "SECURITY ERROR: SECRET_KEY is too weak or uses a default value. "
            "Set a strong SECRET_KEY (≥32 chars) via environment variable."
        )

    # 数据库 URL 校验（禁止 SQLite）
    if "sqlite" in settings.DATABASE_URL.lower():
        raise RuntimeError(
            "SECURITY ERROR: SQLite is not allowed in production. "
            "Set DATABASE_URL to a PostgreSQL instance."
        )

    # 生产环境禁止 DEV_API_KEY
    if settings.DEV_API_KEY:
        raise RuntimeError(
            "SECURITY ERROR: DEV_API_KEY must not be set in production. "
            "Remove it from environment variables."
        )

    # CORS 配置校验（生产环境禁止使用通配符）
    if settings.ENVIRONMENT == "production" and "*" in settings.CORS_ALLOWED_ORIGINS:
        raise RuntimeError(
            "SECURITY ERROR: CORS wildcard (*) is not allowed in production. "
            "Configure specific allowed origins in CORS_ALLOWED_ORIGINS."
        )

    # DEBUG 模式校验（生产环境必须关闭）
    if settings.DEBUG:
        raise RuntimeError(
            "SECURITY ERROR: DEBUG mode must be disabled in production. "
            "Set DEBUG=false in environment variables."
        )

    # Redis 连接校验（生产环境必须配置）
    if settings.use_redis_sentinel and settings.REDIS_SENTINEL_HOSTS:
        logger.info("Redis configured in sentinel mode with %d sentinels",
                   len(settings.REDIS_SENTINEL_HOSTS.split(',')))
    elif not settings.REDIS_URL or "localhost" in settings.REDIS_URL.lower():
        logger.warning(
            "WARNING: Redis URL points to localhost in production. "
            "Ensure this is intentional and properly secured."
        )

    # JWT 密钥校验（与 SECRET_KEY 同等强度，禁止使用开发默认值）
    # 注意：Settings.validate_jwt_secret_key() 在 ENVIRONMENT=="production" 时已自动校验强度和默认值
    try:
        settings.validate_jwt_secret_key()
    except ValueError as e:
        raise RuntimeError(
            f"SECURITY ERROR: {str(e)} "
            f"Set a strong JWT_SECRET_KEY (≥32 chars) via environment variable."
        ) from e

    logger.info("Production security validation passed")


async def _ensure_dev_api_key() -> None:
    """确保开发环境 DEV_API_KEY 在数据库中有对应记录.

    当配置了 DEV_API_KEY 时，在数据库中创建或更新对应的 api_keys 记录，
    使数据库验证路径也能正常工作（不依赖回退逻辑）。
    """
    import logging

    from sqlalchemy import select

    from nexus.db.database import AsyncSessionLocal
    from nexus.models import APIKey, Tenant, User
    from nexus.security.auth import _extract_key_prefix, _hash_api_key

    logger = logging.getLogger(__name__)
    dev_key = settings.DEV_API_KEY
    if not dev_key:
        return

    async with AsyncSessionLocal() as session:
        # 查找 default tenant
        tenant_result = await session.execute(
            select(Tenant).where(Tenant.slug == "default")
        )
        tenant = tenant_result.scalar_one_or_none()
        if not tenant:
            logger.warning("Default tenant not found, skipping dev API key setup")
            return

        # 查找 admin user
        user_result = await session.execute(
            select(User).where(User.tenant_id == tenant.id, User.role == "admin").limit(1)
        )
        user = user_result.scalar_one_or_none()

        key_hash = _hash_api_key(dev_key)
        key_prefix = _extract_key_prefix(dev_key)

        # 检查是否已存在
        existing = await session.execute(
            select(APIKey).where(
                APIKey.tenant_id == tenant.id,
                APIKey.key_hash == key_hash,
            )
        )
        if existing.scalar_one_or_none():
            logger.debug("Dev API key already exists in database")
            return

        # 创建新的 dev API Key 记录
        api_key = APIKey(
            tenant_id=tenant.id,
            user_id=user.id if user else None,
            name="Development API Key (auto-generated)",
            key_hash=key_hash,
            key_prefix=key_prefix,
            permissions=["*"],
            rate_limit=1000,
        )
        session.add(api_key)
        await session.commit()
        logger.info("Created dev API key record in database (prefix=%s)", key_prefix)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理.

    初始化顺序:
    1. 数据库
    2. ARQ Redis 连接池
    3. Redis 客户端（EventBus + 通用缓存）
    4. EventBus（带 Redis Pub/Sub）
    5. WebSocket 桥接（EventBus → WebSocket）
    6. EventBus Redis 监听（后台任务，接收 Worker 事件）
    """
    # 启动
    await init_db()

    # OpenTelemetry 链路追踪（graceful degradation when disabled or SDK missing）
    from nexus.observability.tracing import setup_tracing
    tracer = setup_tracing()
    if tracer:
        app.state.tracer = tracer

    # 应用启动时自动运行安全校验（所有环境）
    # 生产环境执行完整校验，开发/测试环境仅执行基础校验
    if settings.ENVIRONMENT == "production":
        _validate_production_security()
    else:
        # 非生产环境也进行基础安全检查
        logger = logging.getLogger(__name__)
        if settings.DEV_API_KEY:
            logger.warning(
                "DEV_API_KEY is set in %s environment. "
                "This is acceptable for development but should NEVER be used in production.",
                settings.ENVIRONMENT,
            )

    # 确保开发环境 API Key 在数据库中有记录（DEV_API_KEY 回退需要）
    if settings.DEV_API_KEY and settings.ENVIRONMENT != "production":
        await _ensure_dev_api_key()

    await init_arq_pool()

    # Redis 客户端（用于 EventBus 和通用缓存）- 支持哨兵模式
    if settings.use_redis_sentinel and settings.REDIS_SENTINEL_HOSTS:
        from nexus.cache.redis_client import get_redis_client
        redis_client = get_redis_client()
    else:
        redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    app.state.redis = redis_client

    # EventBus（带 Redis，用于跨进程通信）
    event_bus = EventBus(redis_client=redis_client)
    app.state.event_bus = event_bus

    # WebSocket 桥接：EventBus 事件 → WebSocket 推送
    from nexus.api.websocket import manager, subscribe_websocket_to_eventbus
    subscribe_websocket_to_eventbus(event_bus, manager)

    # 启动 Redis Pub/Sub 监听（后台任务）
    # 这是跨进程通信的关键：Worker publish → Redis → API listener → WebSocket
    listener_task = asyncio.create_task(event_bus.start_listener())

    # 注册 RAG Tools（Smart Cache 集成）
    # 使用全局单例，确保 API 进程和 Worker 进程共享同一 ToolRegistry
    from nexus.tools.registry import get_tool_registry

    tool_registry = get_tool_registry()
    app.state.tool_registry = tool_registry

    # 初始化 MCP Client Manager（绑定 ToolRegistry）
    from nexus.mcp.client import get_mcp_client_manager

    mcp_client_mgr = get_mcp_client_manager(tool_registry=tool_registry)
    app.state.mcp_client_manager = mcp_client_mgr

    # 可选：启动内置 MCP Server（后台任务，独立端口）
    mcp_server_task = None
    if settings.MCP_SERVER_ENABLED:
        from nexus.mcp.server import NexusMCPServer

        mcp_server = NexusMCPServer(tool_registry, name="nexus")
        mcp_server_task = asyncio.create_task(
            mcp_server.run_async(
                transport="sse",
                port=settings.MCP_SERVER_PORT,
                host=settings.MCP_SERVER_HOST,
            )
        )
        app.state.mcp_server = mcp_server

    yield

    # 关闭（逆序）
    if mcp_server_task:
        mcp_server_task.cancel()
        try:
            await mcp_server_task
        except asyncio.CancelledError:
            pass

    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass

    await redis_client.close()
    await close_arq_pool()
    await close_db()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Enterprise Multi-Agent Orchestration Engine",
    lifespan=lifespan,
)


# 修复 (前端 307 丢 auth): 浏览器 GET /api/v1/tools (无尾斜杠) 之前 FastAPI
# 回 307 → /api/v1/tools/, 但浏览器规范: 跨源 307 不保留 sensitive headers
# (Authorization 算 sensitive), 第二次请求没 token → 401 → 跳 /login。
# 解法: 中间件在内部把 /api/v1/tools 改写到 /api/v1/tools/, 避免 307。
# 注意 1: 只对 safe methods (GET/HEAD/OPTIONS) 改写, POST 跟它无关。
# 注意 2: 只对 list-style 集合根改写 (如 /api/v1/tools, /api/v1/agents),
# 绝对不能改写子路径 (如 /api/v1/dashboard/stats, /api/v1/runs/xxx),
# 否则 FastAPI 找不到路由会无限重定向。
_TRAILING_SLASH_LIST_PATHS = frozenset({
    "/api/v1/agents",
    "/api/v1/workflows",
    "/api/v1/tools",
    "/api/v1/crews",
    # 注: /api/v1/runs /dashboard/stats /evals /mcp /hitl /prompts /traces
    # 这些 router 在 runs.py / dashboard.py 等用 @router.get("") 注册, canonical
    # 路径无尾斜杠。如果加到上面集合, 中间件会改写到 /runs/, 但 router 里没
    # / 路径, FastAPI 再 307 回去, 死循环。
    "/api/v1/agents",
    "/api/v1/workflows",
    "/api/v1/tools",
    "/api/v1/crews",
})


@app.middleware("http")
async def _normalize_trailing_slash(request: Request, call_next):
    if request.method in ("GET", "HEAD", "OPTIONS"):
        path = request.url.path
        # 严格匹配: path 必须在已知 list 路径里
        if path in _TRAILING_SLASH_LIST_PATHS:
            new_path = path + "/"
            request.scope["path"] = new_path
            # raw_path 是 ASGI 层的 byte string, 必须包含 query string (如果有)
            # 不然 query 丢了。但 query string 在 scope["query_string"] 里,
            # raw_path 只要 path 部分。
            request.scope["raw_path"] = new_path.encode("latin-1")
    return await call_next(request)

# CORS中间件
_cors_origins = (
    ["*"]
    if settings.ENVIRONMENT == "development"
    else settings.CORS_ALLOWED_ORIGINS
)
# 修复 (前端 CORS Bug): CORS 中间件必须最外层, 否则 OPTIONS preflight
# 先被 RBAC 看到, 没有 auth header → 401, 没有 CORS headers, 浏览器 CORS error。
# FastAPI add_middleware 是反向入栈 (后加的在外), 所以 CORS 必须最后 add。
# 顺序: Prometheus (最内) → RBAC → CORS (最外)
# RBAC 顺序: 先于 Prometheus 是为了让 RBAC 不被 Prometheus 中间件拦截 metric

# RBAC 中间件 (先加, 在内层)
app.add_middleware(RBACMiddleware)

# Prometheus 指标中间件 (中间层)
from nexus.observability.metrics import PrometheusMiddleware, metrics_endpoint
app.add_middleware(PrometheusMiddleware)

# CORS 中间件 (最后加, 最外层 — OPTIONS preflight 一定先到这里)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 全局异常处理
@app.exception_handler(NexusException)
async def nexus_exception_handler(request: Request, exc: NexusException):
    """处理NEXUS自定义异常.
    
    返回结构化的错误响应，包含错误码、消息和详细信息。
    响应格式:
    {
        "success": false,
        "error": {
            "code": 1500,
            "name": "INTERNAL_SERVER_ERROR",
            "message": "错误描述",
            "details": {}
        }
    }
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": exc.error_code.value if hasattr(exc, 'error_code') else 1500,
                "name": exc.code if hasattr(exc, 'code') else "UNKNOWN_ERROR",
                "message": exc.message,
                "details": exc.details if hasattr(exc, 'details') else {},
            },
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """处理Pydantic请求参数校验异常.

    返回结构化的422错误，包含详细的字段验证失败信息。
    响应格式:
    {
        "success": false,
        "error": {
            "code": 1401,
            "name": "VALIDATION_INVALID_INPUT",
            "message": "Request validation failed",
            "details": {
                "errors": [...]
            }
        }
    }
    """
    errors = []
    for err in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in err.get("loc", [])),
            "message": err.get("msg", ""),
            "type": err.get("type", ""),
        })
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": {
                "code": 1401,
                "name": "VALIDATION_INVALID_INPUT",
                "message": "Request validation failed",
                "details": {"errors": errors},
            },
        },
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    """处理SQLAlchemy数据库异常.

    返回503 Service Unavailable，不暴露底层数据库错误详情。
    响应格式:
    {
        "success": false,
        "error": {
            "code": 1302,
            "name": "DB_QUERY_ERROR",
            "message": "Database service temporarily unavailable",
            "details": {}
        }
    }
    """
    import logging

    logger = logging.getLogger(__name__)
    logger.error("Database error: %s", exc, exc_info=True)

    return JSONResponse(
        status_code=503,
        content={
            "success": False,
            "error": {
                "code": 1302,
                "name": "DB_QUERY_ERROR",
                "message": "Database service temporarily unavailable",
                "details": {},
            },
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局兜底异常处理器.

    捕获所有未处理的异常，返回500错误但绝不暴露堆栈或内部实现细节。
    响应格式:
    {
        "success": false,
        "error": {
            "code": 1500,
            "name": "INTERNAL_SERVER_ERROR",
            "message": "An internal server error occurred",
            "details": {}
        }
    }
    """
    import logging

    logger = logging.getLogger(__name__)
    logger.error("Unhandled exception: %s", exc, exc_info=True)

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {
                "code": 1500,
                "name": "INTERNAL_SERVER_ERROR",
                "message": "An internal server error occurred",
                "details": {},
            },
        },
    )


# 健康检查
@app.get("/health")
async def health():
    """健康检查端点."""
    return {"status": "ok", "version": settings.APP_VERSION}


# Prometheus 指标端点
@app.get("/metrics")
async def metrics():
    """Prometheus 指标抓取端点."""
    return await metrics_endpoint()


# 导入并注册路由（使用Service层）
from nexus.api.routes import workflows, agents, tools, runs, hitl_tasks, mcp, traces, prompts, evals, code_review, github_webhook, crews, auto, auth, dashboard
# 别名: 不能用 `settings` 直接 import, 会跟 `from nexus.config import settings` 撞名
from nexus.api.routes import settings as settings_router  # noqa: E402
from nexus.api.websocket import router as websocket_router

app.include_router(workflows.router, prefix="/api/v1/workflows", tags=["workflows"])
app.include_router(agents.router, prefix="/api/v1/agents", tags=["agents"])
app.include_router(tools.router, prefix="/api/v1/tools", tags=["tools"])
app.include_router(runs.router, prefix="/api/v1/runs", tags=["runs"])
app.include_router(hitl_tasks.router, prefix="/api/v1/hitl", tags=["hitl"])
app.include_router(mcp.router, prefix="/api/v1/mcp", tags=["mcp"])
app.include_router(traces.router, prefix="/api/v1/traces", tags=["traces"])
app.include_router(prompts.router, prefix="/api/v1/prompts", tags=["prompts"])
app.include_router(evals.router, prefix="/api/v1/evals", tags=["evals"])
app.include_router(code_review.router, prefix="/api/v1/code-review", tags=["code-review"])
app.include_router(github_webhook.router, prefix="/api/v1", tags=["github"])
app.include_router(crews.router, prefix="/api/v1/crews", tags=["crews"])
app.include_router(auto.router, prefix="/api/v1/auto", tags=["auto"])
# 修复 (前端 Settings.vue 404): 注册 settings router, 提供 /api/v1/settings + /api-keys
app.include_router(settings_router.router, prefix="/api/v1/settings", tags=["settings"])
app.include_router(settings_router.api_keys_router, prefix="/api/v1", tags=["api-keys"])
app.include_router(auth.router, prefix="/api/v1", tags=["authentication"])  # Auth路由
app.include_router(dashboard.router, prefix="/api/v1", tags=["dashboard"])  # Dashboard统计路由
app.include_router(websocket_router)  # WebSocket 路由（路径已在 router 中定义）


@app.get("/")
async def root():
    """根路径."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }

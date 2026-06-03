"""FastAPI主应用.

基于WAT api/app.py 升级:
- 复用FastAPI结构
- 扩展为多租户API
- 增加MCP Gateway支持
- 集成OpenTelemetry
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from nexus.config import settings
from nexus.db.database import close_db, init_db
from nexus.engine.event_bus import EventBus
from nexus.exceptions import NexusException
from nexus.jobs.pool import close_arq_pool, init_arq_pool
from nexus.security.rbac import RBACMiddleware


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
    await init_arq_pool()

    # Redis 客户端（用于 EventBus 和通用缓存）
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

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# RBAC中间件
app.add_middleware(RBACMiddleware)

# Prometheus 指标中间件
from nexus.observability.metrics import PrometheusMiddleware, metrics_endpoint
app.add_middleware(PrometheusMiddleware)


# 全局异常处理
@app.exception_handler(NexusException)
async def nexus_exception_handler(request: Request, exc: NexusException):
    """处理NEXUS自定义异常."""
    return JSONResponse(
        status_code=400,
        content={"detail": exc.message, "code": exc.code},
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
from nexus.api.routes import workflows, agents, tools, runs, hitl_tasks, mcp, traces, prompts, evals, code_review
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
app.include_router(websocket_router)  # WebSocket 路由（路径已在 router 中定义）


@app.get("/")
async def root():
    """根路径."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }

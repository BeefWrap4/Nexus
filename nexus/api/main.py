"""FastAPI主应用.

基于WAT api/app.py 升级:
- 复用FastAPI结构
- 扩展为多租户API
- 增加MCP Gateway支持
- 集成OpenTelemetry
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from nexus.config import settings
from nexus.db.database import close_db, init_db
from nexus.exceptions import NexusException
from nexus.security.rbac import RBACMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理."""
    # 启动
    await init_db()
    yield
    # 关闭
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


# 导入并注册路由（使用Service层）
from nexus.api.routes import workflows, agents, tools, runs, hitl_tasks

app.include_router(workflows.router, prefix="/api/v1/workflows", tags=["workflows"])
app.include_router(agents.router, prefix="/api/v1/agents", tags=["agents"])
app.include_router(tools.router, prefix="/api/v1/tools", tags=["tools"])
app.include_router(runs.router, prefix="/api/v1/runs", tags=["runs"])
app.include_router(hitl_tasks.router, prefix="/api/v1/hitl", tags=["hitl"])


@app.get("/")
async def root():
    """根路径."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }

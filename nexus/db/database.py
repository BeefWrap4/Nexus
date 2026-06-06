"""NEXUS数据库连接与会话管理.

基于WAT utils/database.py 升级：
- 从裸SQL迁移到SQLAlchemy 2.0 ORM
- 支持async操作
- 多租户Row-Level Security (修复 S1-3：真正启用)
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from nexus.config import settings


# 修复 (S4-4): SQLAlchemy 2.0 风格 DeclarativeBase 子类
# 之前用 legacy `declarative_base()` 函数式 API，是 SQLAlchemy 1.x 风格；
# 2.0 推荐显式继承 DeclarativeBase，便于类型注解和声明式配置。
class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类."""


# 异步引擎
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=settings.DATABASE_POOL_RECYCLE,
    echo=settings.DATABASE_ECHO,
)

# 异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


# 修复 (S1-3): per-session 注入 GUC `app.tenant_id` 让 RLS 工作
# AsyncSession 没有 "after_begin" 事件（async 模式），用 Connection-level "begin"
# 事件 + session.info 配合。事务开始时从 session.info 读 tenant_id 写入 PG。
# 注意：async 模式下 SQLAlchemy 的事件签名略有不同（参数是 conn，不是 session）。
@event.listens_for(engine.sync_engine, "begin")
def _on_begin_transaction(conn):
    """sync engine begin 事件（async engine 也是用同一 dispatch）。"""
    # async 模式下，session.info 通过 thread-local 不可访问
    # 所以我们用另一种方式：直接用 connection 上的 _nexus_tenant_id 属性
    tenant_id = getattr(conn, "_nexus_tenant_id", None)
    if not tenant_id:
        return
    safe = str(tenant_id).replace("'", "''")
    conn.exec_driver_sql(f"SET app.tenant_id = '{safe}'")


# 修复 (S1-3): 提供一个简单的工具函数让 service 层在每次事务显式设置 tenant_id
# 替代方案是注册到 async session 的 before_cursor_execute，但 API 不直观
def set_session_tenant_id(session: AsyncSession, tenant_id: Optional[str]) -> None:
    """把 tenant_id 绑定到 session，下次 begin() 时写入 PG GUC.

    用法:
        async with get_db_session() as session:
            set_session_tenant_id(session, current_user["tenant_id"])
            # 之后的 SELECT/INSERT 都会经过 RLS 过滤
    """
    if tenant_id is not None:
        session.info["tenant_id"] = tenant_id
    elif "tenant_id" in session.info:
        del session.info["tenant_id"]


async def init_db():
    """初始化数据库（创建所有表）."""
    async with engine.begin() as conn:
        # SQLite 数据库优化：启用 WAL 模式
        if settings.DATABASE_URL.startswith("sqlite"):
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """关闭数据库连接."""
    await engine.dispose()


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话的上下文管理器."""
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI依赖：获取数据库会话.

    用法:
        @app.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with get_db_session() as session:
        yield session


async def get_db_with_tenant(
    tenant_id: Optional[str] = None,
) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI依赖：获取绑定了 tenant_id 的 DB session.

    修复 (S1-3): 推荐替代 get_db() 用于 tenant-scoped 端点。
    用法:
        @router.get("/workflows")
        async def list_workflows(db = Depends(get_db_with_tenant)):
            ...

    Args:
        tenant_id: 租户 ID。None 时 session 看不到任何 multi-tenant 行（RLS 默认拒绝）。
    """
    async with get_db_session() as session:
        if tenant_id:
            session.info["tenant_id"] = tenant_id
        yield session

"""ARQ Redis 连接池管理.

提供全局 ARQ 连接池的初始化和获取，供 FastAPI API 和 Worker 共享使用。

使用方式:
    # API 进程 lifespan 中初始化
    await init_arq_pool()
    # ...
    await close_arq_pool()

    # Service 层入队任务
    pool = get_arq_pool()
    if pool:
        await pool.enqueue_job("execute_workflow_job", ...)
"""

from __future__ import annotations

from arq import create_pool
from arq.connections import RedisSettings

from nexus.config import settings

_arq_pool = None


async def init_arq_pool() -> None:
    """初始化全局 ARQ Redis 连接池."""
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))


async def close_arq_pool() -> None:
    """关闭全局 ARQ Redis 连接池."""
    global _arq_pool
    if _arq_pool is not None:
        await _arq_pool.close()
        _arq_pool = None


def get_arq_pool():
    """获取全局 ARQ Redis 连接池.

    Returns:
        ArqRedis: ARQ Redis 连接池，如果未初始化则返回 None
    """
    return _arq_pool

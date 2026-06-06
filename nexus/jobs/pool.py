"""ARQ Redis 连接池管理.

修复 (S1-2): 用真实的 Sentinel 客户端发现 master，替代硬编码 host='redis-master'。

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

import logging
from typing import Optional

from arq import create_pool
from arq.connections import RedisSettings
from redis.asyncio.sentinel import Sentinel

from nexus.config import settings

logger = logging.getLogger(__name__)

_arq_pool = None
_resolved_master: Optional[tuple[str, int]] = None  # (host, port) 缓存


async def _resolve_master_via_sentinel() -> tuple[str, int]:
    """通过 Sentinel 集群发现当前 master 节点.

    修复 (S1-2): 之前硬编码 host='redis-master'，failover 后所有 worker 仍指向旧 IP。
    现在用 redis.asyncio.sentinel.Sentinel.discover_master() 实时发现。

    Returns:
        (host, port) 元组，例如 ('10.0.0.5', 6379)
    """
    if not (settings.use_redis_sentinel and settings.REDIS_SENTINEL_HOSTS):
        # 单节点模式：直接用 REDIS_URL
        from urllib.parse import urlparse
        parsed = urlparse(settings.REDIS_URL or 'redis://localhost:6379/0')
        host = parsed.hostname or 'localhost'
        port = parsed.port or 6379
        return (host, port)

    # 哨兵模式：解析 sentinels 列表 (host:port 逗号分隔)
    sentinel_hosts = []
    for entry in settings.REDIS_SENTINEL_HOSTS.split(','):
        entry = entry.strip()
        if not entry:
            continue
        host, _, port = entry.partition(':')
        sentinel_hosts.append((host, int(port or 26379)))

    sentinel = Sentinel(
        sentinel_hosts,
        password=settings.REDIS_PASSWORD,
        sentinel_kwargs={"password": settings.REDIS_PASSWORD},
    )

    try:
        # discover_master() 内部会问每个 sentinel +sdown/-odown 状态确认主节点
        master = await sentinel.discover_master(settings.REDIS_SENTINEL_MASTER)
        # master 是 (host, port) tuple
        logger.info(
            "redis_master_resolved_via_sentinel master=%s:%d sentinels=%d",
            master[0], master[1], len(sentinel_hosts),
        )
        return (master[0], master[1])
    except Exception as e:
        # 哨兵不可用：fallback 到硬编码 host（保持向后兼容）
        logger.error(
            "redis_sentinel_discovery_failed err=%s fallback=redis-master:6379",
            str(e),
        )
        return ("redis-master", 6379)


async def init_arq_pool() -> None:
    """初始化全局 ARQ Redis 连接池.

    修复 (S1-2): 通过 Sentinel 实时发现 master 节点地址，避免硬编码。
    """
    global _arq_pool, _resolved_master
    if _arq_pool is not None:
        return

    host, port = await _resolve_master_via_sentinel()
    _resolved_master = (host, port)

    redis_settings = RedisSettings(
        host=host,
        port=port,
        password=settings.REDIS_PASSWORD,
    )

    _arq_pool = await create_pool(redis_settings)
    logger.info("arq_pool_initialized", host=host, port=port)


async def reinit_arq_pool_after_failover() -> None:
    """Failover 后重新初始化 ARQ 池.

    修复 (S1-2): 当旧 master 挂了，sentinel 会把另一台 replica 提升为 master。
    ARQ 池仍指向旧地址会一直连接失败。调用方可以在 health check 失败时
    调本函数重新发现 master。
    """
    global _arq_pool
    if _arq_pool is not None:
        try:
            await _arq_pool.aclose()
        except Exception:
            logger.warning("arq_pool_close_failed_during_failover", exc_info=True)
    _arq_pool = None
    await init_arq_pool()
    logger.info("arq_pool_reinitialized_after_failover", new_master=_resolved_master)


async def close_arq_pool() -> None:
    """关闭全局 ARQ Redis 连接池."""
    global _arq_pool
    if _arq_pool is not None:
        await _arq_pool.aclose()
        _arq_pool = None
    _resolved_master = None


def get_arq_pool():
    """获取全局 ARQ Redis 连接池.

    Returns:
        ArqRedis: ARQ Redis 连接池，如果未初始化则返回 None
    """
    return _arq_pool


def get_resolved_master() -> Optional[tuple[str, int]]:
    """获取 Sentinel 解析出的当前 master (host, port)，用于诊断。"""
    return _resolved_master

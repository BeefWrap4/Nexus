"""Redis客户端,支持哨兵模式和单节点模式.

修复 (P0): 之前用 sync `redis` + `redis.sentinel.Sentinel`, 返回的是
同步 redis.Redis 客户端, 但 app.state.redis 之后被 RateLimiter / EventBus
/ state_manager 等按 await self.redis.* 的 async 方式用, 导致
pipe.execute() 返回 list 不能 await, 所有带 JWT 的 API 都 500。

现在用 redis.asyncio.sentinel.Sentinel, master_for() 同步返回 async Redis
对象 (第一次网络访问才发命令), 与 app 其它地方一致。
"""
from redis.asyncio import Redis
from redis.asyncio.sentinel import Sentinel


def get_redis_client():
    """获取Redis客户端,支持哨兵模式.

    如果配置了REDIS_SENTINEL_HOSTS,则使用哨兵模式连接;
    否则使用单节点模式(向后兼容).

    Returns:
        redis.asyncio.Redis: 异步 Redis 客户端实例 (app.state.redis 通用)
    """
    from nexus.config import settings

    if settings.REDIS_SENTINEL_HOSTS:
        # 哨兵模式
        sentinel_hosts = []
        for entry in settings.REDIS_SENTINEL_HOSTS.split(','):
            entry = entry.strip()
            if not entry:
                continue
            host, _, port = entry.partition(':')
            sentinel_hosts.append((host, int(port or 26379)))
        # 修复 (P0): sentinel 本身的 API 是 noauth (default user 'on nopass'),
        # 但被它监控的 master 需要密码。**绝不能**把 master 密码传到
        # sentinel_kwargs, 否则 redis-py 会用 master 密码对 sentinel 做 AUTH,
        # sentinel 会回 "AUTH called without any password configured"。
        # Master 密码走下面 master_for(password=...) 的参数。
        sentinel = Sentinel(
            sentinel_hosts,
            socket_timeout=0.5,
        )
        # master_for 同步返回, 网络访问在第一次 execute 时才发生
        return sentinel.master_for(
            settings.REDIS_SENTINEL_MASTER,
            password=settings.REDIS_PASSWORD,
            socket_timeout=0.5,
            decode_responses=True,
        )
    else:
        # 单节点模式(向后兼容) - 同步 URL 解析, 异步 Redis 对象
        from urllib.parse import urlparse
        parsed = urlparse(settings.REDIS_URL or "redis://localhost:6379/0")
        return Redis(
            host=parsed.hostname or "localhost",
            port=parsed.port or 6379,
            password=(
                settings.REDIS_PASSWORD
                if getattr(settings, "REDIS_PASSWORD", None) else None
            ),
            decode_responses=True,
        )

"""Redis客户端,支持哨兵模式和单节点模式."""

import redis
from redis.sentinel import Sentinel


def get_redis_client():
    """获取Redis客户端,支持哨兵模式.
    
    如果配置了REDIS_SENTINEL_HOSTS,则使用哨兵模式连接;
    否则使用单节点模式(向后兼容).
    
    Returns:
        redis.Redis: Redis客户端实例
    
    Examples:
        >>> client = get_redis_client()
        >>> client.set("key", "value")
        >>> client.get("key")
        'value'
    """
    from nexus.config import settings
    
    if settings.REDIS_SENTINEL_HOSTS:
        # 哨兵模式
        sentinel_hosts = [
            tuple(host.split(':'))
            for host in settings.REDIS_SENTINEL_HOSTS.split(',')
        ]
        sentinel = Sentinel(sentinel_hosts, socket_timeout=0.5)
        master = sentinel.master_for(
            settings.REDIS_SENTINEL_MASTER,
            password=settings.REDIS_PASSWORD,
            socket_timeout=0.5,
            decode_responses=True
        )
        return master
    else:
        # 单节点模式(向后兼容)
        return redis.Redis(
            host='localhost',
            port=6379,
            password=settings.REDIS_PASSWORD if hasattr(settings, 'REDIS_PASSWORD') and settings.REDIS_PASSWORD else None,
            decode_responses=True
        )

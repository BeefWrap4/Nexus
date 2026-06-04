"""Redis缓存服务 - 优化workflow定义和agent配置读取性能.

使用Redis缓存频繁访问的数据，减少数据库查询次数，提高系统响应速度。
"""

import json
import logging
from typing import Any, Optional

import redis.asyncio as redis

from nexus.config import settings

logger = logging.getLogger(__name__)


class RedisCacheService:
    """Redis缓存服务.

    提供：
    1. Workflow定义缓存（TTL: 300秒）
    2. Agent配置缓存（TTL: 600秒）
    3. 通用键值缓存
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or getattr(settings, 'REDIS_URL', 'redis://localhost:6379/0')
        self._redis_client: Optional[redis.Redis] = None

        # 缓存TTL配置（秒）
        self.WORKFLOW_CACHE_TTL = 300  # 5分钟
        self.AGENT_CONFIG_CACHE_TTL = 600  # 10分钟
        self.DEFAULT_CACHE_TTL = 300  # 5分钟

    async def _get_client(self) -> redis.Redis:
        """获取Redis客户端（懒加载）."""
        if self._redis_client is None:
            try:
                self._redis_client = redis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                # 测试连接
                await self._redis_client.ping()
                logger.info("Redis连接成功")
            except Exception as e:
                logger.warning(f"Redis连接失败，将不使用缓存: {e}")
                self._redis_client = None

        return self._redis_client

    async def get(self, key: str) -> Optional[Any]:
        """从缓存获取数据.

        Args:
            key: 缓存键

        Returns:
            缓存的值，如果不存在或出错则返回None
        """
        try:
            client = await self._get_client()
            if client is None:
                return None

            value = await client.get(key)
            if value is None:
                return None

            # 尝试反序列化JSON
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value

        except Exception as e:
            logger.warning(f"Redis GET失败: {key}, 错误: {e}")
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> bool:
        """设置缓存.

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），默认使用DEFAULT_CACHE_TTL

        Returns:
            是否成功
        """
        try:
            client = await self._get_client()
            if client is None:
                return False

            # 序列化值
            if isinstance(value, (dict, list)):
                serialized = json.dumps(value)
            else:
                serialized = str(value)

            ttl = ttl or self.DEFAULT_CACHE_TTL
            await client.setex(key, ttl, serialized)
            return True

        except Exception as e:
            logger.warning(f"Redis SET失败: {key}, 错误: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """删除缓存.

        Args:
            key: 缓存键

        Returns:
            是否成功
        """
        try:
            client = await self._get_client()
            if client is None:
                return False

            await client.delete(key)
            return True

        except Exception as e:
            logger.warning(f"Redis DELETE失败: {key}, 错误: {e}")
            return False

    async def get_workflow_definition(self, workflow_id: str) -> Optional[dict]:
        """获取Workflow定义缓存.

        Args:
            workflow_id: Workflow ID

        Returns:
            Workflow定义字典，如果不存在则返回None
        """
        cache_key = f"workflow:def:{workflow_id}"
        return await self.get(cache_key)

    async def set_workflow_definition(
        self,
        workflow_id: str,
        definition: dict,
    ) -> bool:
        """设置Workflow定义缓存.

        Args:
            workflow_id: Workflow ID
            definition: Workflow定义字典

        Returns:
            是否成功
        """
        cache_key = f"workflow:def:{workflow_id}"
        return await self.set(cache_key, definition, self.WORKFLOW_CACHE_TTL)

    async def invalidate_workflow_cache(self, workflow_id: str) -> bool:
        """使Workflow缓存失效（当workflow被更新时调用）.

        Args:
            workflow_id: Workflow ID

        Returns:
            是否成功
        """
        cache_key = f"workflow:def:{workflow_id}"
        return await self.delete(cache_key)

    async def get_agent_config(self, agent_name: str) -> Optional[dict]:
        """获取Agent配置缓存.

        Args:
            agent_name: Agent名称

        Returns:
            Agent配置字典，如果不存在则返回None
        """
        cache_key = f"agent:config:{agent_name}"
        return await self.get(cache_key)

    async def set_agent_config(
        self,
        agent_name: str,
        config: dict,
    ) -> bool:
        """设置Agent配置缓存.

        Args:
            agent_name: Agent名称
            config: Agent配置字典

        Returns:
            是否成功
        """
        cache_key = f"agent:config:{agent_name}"
        return await self.set(cache_key, config, self.AGENT_CONFIG_CACHE_TTL)

    async def invalidate_agent_cache(self, agent_name: str) -> bool:
        """使Agent配置缓存失效（当agent配置被更新时调用）.

        Args:
            agent_name: Agent名称

        Returns:
            是否成功
        """
        cache_key = f"agent:config:{agent_name}"
        return await self.delete(cache_key)

    async def get_cache_stats(self) -> dict:
        """获取缓存统计信息.

        Returns:
            包含缓存命中率和性能的统计信息
        """
        try:
            client = await self._get_client()
            if client is None:
                return {"status": "unavailable"}

            info = await client.info("stats")
            return {
                "status": "available",
                "hits": info.get("keyspace_hits", 0),
                "misses": info.get("keyspace_misses", 0),
                "hit_rate": self._calculate_hit_rate(
                    info.get("keyspace_hits", 0),
                    info.get("keyspace_misses", 0),
                ),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "N/A"),
            }

        except Exception as e:
            logger.warning(f"获取缓存统计失败: {e}")
            return {"status": "error", "error": str(e)}

    @staticmethod
    def _calculate_hit_rate(hits: int, misses: int) -> float:
        """计算缓存命中率.

        Args:
            hits: 命中次数
            misses: 未命中次数

        Returns:
            命中率（0-1）
        """
        total = hits + misses
        if total == 0:
            return 0.0
        return hits / total

    async def close(self):
        """关闭Redis连接."""
        if self._redis_client:
            await self._redis_client.close()
            self._redis_client = None
            logger.info("Redis连接已关闭")


# 全局缓存服务实例
_cache_service: Optional[RedisCacheService] = None


def get_cache_service() -> RedisCacheService:
    """获取全局缓存服务实例."""
    global _cache_service
    if _cache_service is None:
        _cache_service = RedisCacheService()
    return _cache_service


def reset_cache_service():
    """重置全局缓存服务（用于测试）."""
    global _cache_service
    if _cache_service:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_cache_service.close())
            else:
                loop.run_until_complete(_cache_service.close())
        except Exception:
            pass
    _cache_service = None

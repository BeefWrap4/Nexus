"""API Key速率限制器.

基于Redis Sorted Set的滑动窗口算法实现。

工作原理:
- 使用Redis Sorted Set存储每个API Key的请求时间戳
- Sorted Set的score为请求时间戳，member为唯一标识符
- 每次请求时移除过期记录（超出时间窗口的）
- 统计当前窗口内的请求数量
- 如果超过限制则拒绝请求并返回429状态码
- 响应头包含X-RateLimit-*信息供客户端参考
"""

import time
from typing import Optional

from fastapi import HTTPException
from redis.asyncio import Redis


class RateLimiter:
    """基于Redis滑动窗口的速率限制器."""

    def __init__(self, redis_client: Redis):
        """初始化速率限制器.

        Args:
            redis_client: Redis异步客户端实例
        """
        self.redis = redis_client

    async def check_rate_limit(
        self,
        api_key: str,
        limit: int,
        window: int = 60,  # 默认60秒窗口
    ) -> dict:
        """检查API Key是否在速率限制内.

        使用滑动窗口算法:
        1. 计算当前时间窗口的起始时间
        2. 移除窗口外的旧记录
        3. 统计窗口内的请求数
        4. 如果超限则抛出429异常
        5. 否则记录当前请求并返回剩余配额

        Args:
            api_key: API密钥
            limit: 允许的最大请求数
            window: 时间窗口(秒)

        Returns:
            dict: {
                "allowed": bool,      # 是否允许请求
                "remaining": int,     # 剩余请求数
                "reset_at": float     # 窗口重置时间戳
            }

        Raises:
            HTTPException: 429 Too Many Requests (当超出速率限制时)

        Example:
            >>> limiter = RateLimiter(redis_client)
            >>> result = await limiter.check_rate_limit("nexus_xxx", limit=100, window=60)
            >>> print(f"Remaining: {result['remaining']}")
        """
        key = f"rate_limit:{api_key}"
        now = time.time()
        window_start = now - window

        # 使用pipeline批量执行，减少网络往返
        pipe = self.redis.pipeline()

        # 移除过期记录（窗口开始时间之前的所有记录）
        pipe.zremrangebyscore(key, 0, window_start)

        # 获取当前窗口内的请求数
        pipe.zcard(key)

        # 执行批量命令
        results = await pipe.execute()
        current_count = results[1]  # zcard的结果

        if current_count >= limit:
            # 获取最早记录的过期时间作为reset_at
            oldest = await self.redis.zrange(key, 0, 0, withscores=True)
            reset_at = oldest[0][1] + window if oldest else now + window

            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(reset_at)),
                    "Retry-After": str(int(reset_at - now)),
                },
            )

        # 添加当前请求记录
        # 使用唯一ID作为member避免冲突（时间戳+随机数）
        member_id = f"{now}:{time.monotonic_ns()}"
        await self.redis.zadd(key, {member_id: now})

        # 设置key的过期时间（比窗口稍长，确保清理）
        await self.redis.expire(key, window + 10)

        remaining = limit - current_count - 1

        return {
            "allowed": True,
            "remaining": max(0, remaining),
            "reset_at": now + window,
        }

    async def get_rate_limit_info(
        self,
        api_key: str,
        limit: int,
        window: int = 60,
    ) -> dict:
        """获取API Key的速率限制信息（不增加计数）.

        用于查询当前使用情况，不影响实际计数。

        Args:
            api_key: API密钥
            limit: 允许的最大请求数
            window: 时间窗口(秒)

        Returns:
            dict: {
                "current_count": int,   # 当前窗口内的请求数
                "remaining": int,       # 剩余请求数
                "limit": int,           # 总限制数
                "window": int,          # 窗口大小(秒)
                "reset_at": float       # 窗口重置时间戳
            }
        """
        key = f"rate_limit:{api_key}"
        now = time.time()
        window_start = now - window

        # 清理过期记录
        await self.redis.zremrangebyscore(key, 0, window_start)

        # 获取当前计数
        current_count = await self.redis.zcard(key)

        # 获取最早记录的时间
        oldest = await self.redis.zrange(key, 0, 0, withscores=True)
        reset_at = oldest[0][1] + window if oldest else now + window

        return {
            "current_count": current_count,
            "remaining": max(0, limit - current_count),
            "limit": limit,
            "window": window,
            "reset_at": reset_at,
        }

    async def reset_rate_limit(self, api_key: str) -> bool:
        """重置API Key的速率限制计数.

        Args:
            api_key: API密钥

        Returns:
            bool: 是否成功删除
        """
        key = f"rate_limit:{api_key}"
        deleted = await self.redis.delete(key)
        return deleted > 0

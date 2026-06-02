"""事件总线 - Pub/Sub模式.

基于WAT GameEngine._event_subscribers 升级:
- 本地回调 + Redis-backed Pub/Sub 混合架构
- Topic-based路由（借鉴AutoGen v0.4+）
- 支持持久化（Redis Streams）和实时广播（Redis Pub/Sub）
"""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nexus.config import settings


@dataclass
class Subscription:
    """订阅句柄."""

    topic: str
    handler: Callable[[dict[str, Any]], Any]


class EventBus:
    """事件总线.

    对应WAT设计:
    - GameEngine._event_subscribers → _local_subscribers
    - _emit_event() → publish()

    跨进程通信:
    - publish() → Redis Pub/Sub → 所有进程收到
    - start_listener() → 在 API 进程中运行，接收 Redis 消息并触发本地 handler
    """

    def __init__(self, redis_client=None):
        self.redis = redis_client
        self._local_subscribers: dict[str, list[Callable[[dict[str, Any]], Any]]] = {}
        self._history: list[dict[str, Any]] = []  # 本地历史（开发环境）
        self._pubsub = None

    async def publish(self, event: dict[str, Any]) -> None:
        """发布事件.

        对应WAT GameEngine._emit_event()。
        """
        # 确保事件有类型
        if "type" not in event:
            event["type"] = "generic"

        # 1. 本地历史记录
        self._history.append(event)

        # 2. 写入Redis Streams + Pub/Sub 广播（生产环境）
        if self.redis:
            tenant_id = event.get("tenant_id", "default")
            try:
                # Streams 持久化
                await self.redis.xadd(
                    f"nexus:events:{tenant_id}",
                    {"data": str(event)},
                )
                # Pub/Sub 实时广播（跨进程）
                await self.redis.publish(
                    f"nexus:events:{tenant_id}",
                    json.dumps(event),
                )
            except Exception:
                # Redis 不可用时不阻塞事件流
                pass

        # 3. 本地广播（WebSocket推送等）
        await self._broadcast_local(event)

    async def _broadcast_local(self, event: dict[str, Any]) -> None:
        """本地广播事件到所有匹配的订阅者."""
        topic = self._get_topic(event)
        handlers: list[Callable] = []

        # 精确匹配
        handlers.extend(self._local_subscribers.get(topic, []))
        # 通配符匹配
        handlers.extend(self._local_subscribers.get("*", []))

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    asyncio.create_task(handler(event))
                else:
                    handler(event)
            except Exception:
                # 事件处理失败不应影响其他订阅者
                pass

    def subscribe(
        self,
        topic: str,
        handler: Callable[[dict[str, Any]], Any],
    ) -> Subscription:
        """订阅Topic.

        对应WAT GameEngine._event_subscribers.append()。
        """
        if topic not in self._local_subscribers:
            self._local_subscribers[topic] = []
        self._local_subscribers[topic].append(handler)
        return Subscription(topic=topic, handler=handler)

    def unsubscribe(self, subscription: Subscription) -> None:
        """取消订阅."""
        handlers = self._local_subscribers.get(subscription.topic, [])
        if subscription.handler in handlers:
            handlers.remove(subscription.handler)

    def _get_topic(self, event: dict[str, Any]) -> str:
        """从事件推断Topic."""
        event_type = event.get("type", "generic")
        run_id = event.get("run_id", "")
        node_id = event.get("node_id", "")

        # 构建层次化topic
        if run_id and node_id:
            return f"run:{run_id}:node:{node_id}"
        elif run_id:
            return f"run:{run_id}"
        return f"type:{event_type}"

    def get_history(
        self,
        topic: str = "*",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """获取事件历史（用于回溯调试）."""
        if topic == "*":
            return self._history[-limit:]
        return [
            e for e in self._history
            if self._get_topic(e) == topic or topic in self._get_topic(e)
        ][-limit:]

    # ------------------------------------------------------------------
    # Redis Pub/Sub 跨进程监听
    # ------------------------------------------------------------------

    async def start_listener(self) -> None:
        """启动 Redis Pub/Sub 监听循环.

        在 API 进程中运行，接收来自 Worker 的事件并触发本地 handler。
        这是跨进程通信的关键：Worker publish → Redis → API listener → WebSocket。
        """
        if not self.redis:
            return

        import structlog
        logger = structlog.get_logger()
        logger.info("event_bus_redis_listener_starting")

        try:
            self._pubsub = self.redis.pubsub()
            await self._pubsub.psubscribe("nexus:events:*")
            logger.info("event_bus_redis_listener_started")

            async for message in self._pubsub.listen():
                if message["type"] == "pmessage":
                    try:
                        event = json.loads(message["data"])
                        await self._broadcast_local(event)
                    except (json.JSONDecodeError, Exception):
                        # 消息解析失败不阻塞
                        pass
        except asyncio.CancelledError:
            logger.info("event_bus_redis_listener_cancelled")
            if self._pubsub:
                await self._pubsub.punsubscribe()
            raise

    async def stop_listener(self) -> None:
        """停止 Redis Pub/Sub 监听循环."""
        if self._pubsub:
            await self._pubsub.punsubscribe()
            self._pubsub = None

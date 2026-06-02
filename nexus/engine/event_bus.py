"""事件总线 - Pub/Sub模式.

基于WAT GameEngine._event_subscribers 升级:
- 从本地回调升级为Redis-backed事件总线
- Topic-based路由（借鉴AutoGen v0.4+）
- 支持持久化和回溯
"""

import asyncio
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
    """

    def __init__(self, redis_client=None):
        self.redis = redis_client
        self._local_subscribers: dict[str, list[Callable[[dict[str, Any]], Any]]] = {}
        self._history: list[dict[str, Any]] = []  # 本地历史（开发环境）

    async def publish(self, event: dict[str, Any]) -> None:
        """发布事件.

        对应WAT GameEngine._emit_event()。
        """
        # 确保事件有类型
        if "type" not in event:
            event["type"] = "generic"

        # 1. 本地历史记录
        self._history.append(event)

        # 2. 写入Redis Streams（生产环境）
        if self.redis:
            tenant_id = event.get("tenant_id", "default")
            await self.redis.xadd(
                f"nexus:events:{tenant_id}",
                {"data": str(event)},  # 简化为字符串存储
            )

        # 3. 本地广播（WebSocket推送）
        topic = self._get_topic(event)
        for handler in self._local_subscribers.get(topic, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    asyncio.create_task(handler(event))
                else:
                    handler(event)
            except Exception:
                # 事件处理失败不应影响其他订阅者
                pass

        # 4. 广播到通配符订阅者
        for handler in self._local_subscribers.get("*", []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    asyncio.create_task(handler(event))
                else:
                    handler(event)
            except Exception:
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

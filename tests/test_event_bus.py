"""EventBus 测试.

覆盖:
- 本地发布/订阅
- Topic 路由
- 通配符订阅
- 历史记录
- 跨进程 Redis Pub/Sub（集成测试）
"""

import pytest

from nexus.engine.event_bus import EventBus, Subscription


class TestEventBusLocal:
    """测试 EventBus 本地功能."""

    @pytest.mark.asyncio
    async def test_publish_and_subscribe(self):
        """发布事件后，订阅者应收到."""
        bus = EventBus()
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe("run:test", handler)
        await bus.publish({"type": "run_started", "run_id": "test"})

        assert len(received) == 1
        assert received[0]["type"] == "run_started"
        assert received[0]["run_id"] == "test"

    @pytest.mark.asyncio
    async def test_wildcard_subscribe(self):
        """通配符订阅应接收所有事件."""
        bus = EventBus()
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe("*", handler)
        await bus.publish({"type": "run_started", "run_id": "r1"})
        await bus.publish({"type": "run_completed", "run_id": "r2"})

        assert len(received) == 2

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        """取消订阅后不应再接收事件."""
        bus = EventBus()
        received = []

        def handler(event):
            received.append(event)

        sub = bus.subscribe("run:test", handler)
        await bus.publish({"type": "run_started", "run_id": "test"})
        assert len(received) == 1

        bus.unsubscribe(sub)
        await bus.publish({"type": "run_started", "run_id": "test"})
        assert len(received) == 1  # 不应增加

    @pytest.mark.asyncio
    async def test_async_handler(self):
        """异步 handler 应能正常工作."""
        import asyncio

        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe("run:test", handler)
        await bus.publish({"type": "run_started", "run_id": "test"})

        # 给 asyncio.create_task 一点时间执行
        await asyncio.sleep(0.05)

        assert len(received) == 1

    def test_get_history(self):
        """历史记录应正确保存."""
        bus = EventBus()
        # 同步调用 publish（不 await，因为历史记录是同步操作）
        import asyncio
        asyncio.run(bus.publish({"type": "run_started", "run_id": "h1"}))
        asyncio.run(bus.publish({"type": "run_completed", "run_id": "h2"}))

        history = bus.get_history(limit=10)
        assert len(history) == 2

    def test_get_history_with_topic_filter(self):
        """Topic 过滤应正确工作."""
        bus = EventBus()
        import asyncio
        asyncio.run(bus.publish({"type": "run_started", "run_id": "t1"}))
        asyncio.run(bus.publish({"type": "node_error", "run_id": "t1", "node_id": "n1"}))

        # run:t1 匹配 run_started (topic=run:t1) 和 node_error (topic=run:t1:node:n1)
        # 因为 "run:t1" in "run:t1:node:n1" 为 True
        run_history = bus.get_history(topic="run:t1", limit=10)
        assert len(run_history) == 2  # 两个事件都匹配 run:t1 前缀


class TestEventBusRedis:
    """测试 EventBus Redis Pub/Sub（需要 Redis 服务）."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_redis_publish_does_not_raise(self):
        """Redis 可用时 publish 不应抛异常."""
        try:
            from redis.asyncio import Redis
            redis = Redis.from_url("redis://localhost:6379/0", decode_responses=True)
            await redis.ping()
        except Exception as exc:
            pytest.skip(f"Redis not available: {exc}")

        bus = EventBus(redis_client=redis)
        await bus.publish({"type": "test", "run_id": "redis-test"})
        await redis.close()

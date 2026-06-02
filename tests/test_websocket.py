"""WebSocket 实时通信测试.

覆盖:
- ping/pong
- EventBus 桥接（EventBus → WebSocket）
- JWT Token 验证
"""

import pytest
from fastapi.testclient import TestClient

from nexus.api.main import app
from nexus.api.websocket import ConnectionManager, manager, subscribe_websocket_to_eventbus
from nexus.engine.event_bus import EventBus


class TestConnectionManager:
    """测试 WebSocket 连接管理器."""

    def test_manager_is_singleton(self):
        """manager 应为全局单例."""
        assert manager is not None
        assert isinstance(manager, ConnectionManager)


class TestWebSocketEndpoint:
    """测试 WebSocket 端点."""

    def test_websocket_ping_pong(self):
        """WebSocket 应能响应 ping."""
        client = TestClient(app)
        with client.websocket_connect("/ws/v1/runs/test-run?token=") as ws:
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_websocket_without_token(self):
        """无 Token 应允许匿名连接."""
        client = TestClient(app)
        with client.websocket_connect("/ws/v1/runs/test-run") as ws:
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"


class TestEventBusToWebSocketBridge:
    """测试 EventBus → WebSocket 桥接."""

    @pytest.mark.asyncio
    async def test_subscribe_websocket_to_eventbus(self):
        """订阅后，EventBus 事件应转发到 WebSocket."""
        bus = EventBus()
        test_manager = ConnectionManager()

        # 模拟 WebSocket 连接
        received_messages = []

        class MockWebSocket:
            async def send_json(self, data):
                received_messages.append(data)

        ws = MockWebSocket()
        test_manager._connections["run-123"] = [ws]

        # 订阅
        subscribe_websocket_to_eventbus(bus, test_manager)

        # 发布事件
        await bus.publish({
            "type": "run_started",
            "run_id": "run-123",
        })

        # 给异步 handler 一点时间
        import asyncio
        await asyncio.sleep(0.01)

        assert len(received_messages) == 1
        assert received_messages[0]["type"] == "run_started"

    @pytest.mark.asyncio
    async def test_bridge_ignores_non_run_events(self):
        """非 run 相关事件不应转发."""
        bus = EventBus()
        test_manager = ConnectionManager()

        received_messages = []

        class MockWebSocket:
            async def send_json(self, data):
                received_messages.append(data)

        ws = MockWebSocket()
        test_manager._connections["run-123"] = [ws]

        subscribe_websocket_to_eventbus(bus, test_manager)

        # 发布非 run 事件（不应被转发）
        await bus.publish({"type": "generic_event", "data": "test"})

        import asyncio
        await asyncio.sleep(0.01)

        assert len(received_messages) == 0

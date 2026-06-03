"""WebSocket实时通信.

基于WAT api/websocket.py 升级:
- 复用架构
- 增加EventBus桥接（跨进程事件→WebSocket推送）
- JWT Token验证
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from nexus.security.auth import AuthService
from nexus.engine.event_bus import EventBus

router = APIRouter()


class ConnectionManager:
    """WebSocket连接管理器."""

    def __init__(self):
        # 按run_id分组的连接
        self._connections: dict[str, list[WebSocket]] = {}
        # 按用户分组的连接
        self._user_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, run_id: str, user_id: str):
        """建立连接."""
        await websocket.accept()

        if run_id not in self._connections:
            self._connections[run_id] = []
        self._connections[run_id].append(websocket)

        if user_id not in self._user_connections:
            self._user_connections[user_id] = []
        self._user_connections[user_id].append(websocket)

    def disconnect(self, websocket: WebSocket, run_id: str, user_id: str):
        """断开连接."""
        if run_id in self._connections:
            if websocket in self._connections[run_id]:
                self._connections[run_id].remove(websocket)

        if user_id in self._user_connections:
            if websocket in self._user_connections[user_id]:
                self._user_connections[user_id].remove(websocket)

    async def broadcast_to_run(self, run_id: str, message: dict):
        """广播到特定运行的所有连接."""
        if run_id not in self._connections:
            return

        disconnected = []
        for ws in self._connections[run_id]:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(ws)

        # 清理断开的连接
        for ws in disconnected:
            self._connections[run_id].remove(ws)

    async def send_to_user(self, user_id: str, message: dict):
        """发送给特定用户的所有连接."""
        if user_id not in self._user_connections:
            return

        disconnected = []
        for ws in self._user_connections[user_id]:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            self._user_connections[user_id].remove(ws)


# 全局连接管理器
manager = ConnectionManager()


def subscribe_websocket_to_eventbus(event_bus: EventBus, conn_mgr: ConnectionManager) -> None:
    """将 WebSocket 连接管理器订阅到 EventBus.

    当 EventBus 收到 run 相关事件时，自动推送到对应 run_id 的 WebSocket 客户端。
    这是跨进程通信的最后一环：Worker → Redis → API EventBus → WebSocket → 浏览器。
    """
    async def forward_to_websocket(event: dict) -> None:
        run_id = event.get("run_id")
        if not run_id:
            return
        # 转发 run 状态相关事件 + 流式 chunk 事件
        if event.get("type") in (
            "run_started",
            "run_state_update",
            "run_completed",
            "run_failed",
            "node_error",
            "hitl_request",
            "hitl_response",
            "hitl_cancelled",
            "stream_chunk",
            "stream_end",
            "crew_step",
            "crew_complete",
            "crew_error",
        ):
            await conn_mgr.broadcast_to_run(run_id, event)

    # 订阅通配符 topic（EventBus 支持精确匹配和 * 通配符）
    event_bus.subscribe("*", forward_to_websocket)


@router.websocket("/ws/v1/runs/{run_id}")
async def workflow_websocket(
    websocket: WebSocket,
    run_id: str,
    token: str = Query(""),
):
    """工作流执行WebSocket.

    客户端通过此连接接收实时执行状态更新和HITL审批请求。
    """
    # JWT Token 验证
    user_id = "anonymous"
    if token:
        try:
            payload = AuthService.verify_token(token)
            user_id = payload.get("sub", "anonymous")
        except Exception:
            await websocket.close(code=4001, reason="Invalid token")
            return

    await manager.connect(websocket, run_id, user_id)

    try:
        while True:
            # 接收客户端消息
            data = await websocket.receive_json()

            # 处理ping
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})

            # 处理HITL响应
            elif data.get("type") == "hitl_response":
                # HITL 响应通过 REST API 处理更合适
                # WebSocket 只负责实时推送，不处理业务逻辑
                # 这里仅转发确认收到
                await websocket.send_json({
                    "type": "hitl_response_ack",
                    "task_id": data.get("task_id"),
                    "status": "forwarded",
                })

    except WebSocketDisconnect:
        manager.disconnect(websocket, run_id, user_id)
    except Exception:
        # 其他异常也应断开连接
        manager.disconnect(websocket, run_id, user_id)
        raise

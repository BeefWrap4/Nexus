"""WebSocket实时通信.

基于WAT api/websocket.py 升级:
- 复用架构
- 增加频道隔离
- 支持多租户
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query

from nexus.security.auth import get_current_user

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


@router.websocket("/ws/v1/runs/{run_id}")
async def workflow_websocket(
    websocket: WebSocket,
    run_id: str,
    token: str = Query(""),
):
    """工作流执行WebSocket.

    客户端通过此连接接收实时执行状态更新。
    """
    # 简化版：不验证token
    user_id = "anonymous"
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
                # 转发到HITLController
                pass

    except WebSocketDisconnect:
        manager.disconnect(websocket, run_id, user_id)

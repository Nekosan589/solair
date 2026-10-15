import asyncio
import json
import logging
from typing import List

from fastapi import WebSocket

logger = logging.getLogger("dashboard.ws")

class WebSocketManager:
    def __init__(self) -> None:
        self._connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)
            logger.info("client connected (%d active)", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)
            logger.info("client disconnected (%d active)", len(self._connections))

    async def broadcast(self, message: str) -> None:
        stale = []
        for connection in list(self._connections):
            try:
                await connection.send_text(message)
            except Exception:
                stale.append(connection)
        for connection in stale:
            self.disconnect(connection)

manager = WebSocketManager()
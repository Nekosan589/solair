from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from webapp.app.services.ws_manager import manager

router = APIRouter()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Clients connect here and just listen -- all data flows
    server -> client via manager.broadcast() in the background task.

    The receive loop below exists mainly to detect disconnects and to
    give you a hook for client -> server messages later (e.g. the
    browser asking to subscribe to a subset of metrics, or send a
    control command).
    """
    await manager.connect(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            # No inbound protocol yet -- extend here if you need one.
            # Example: echo it back for a manual ping/pong test.
            _ = message
    except WebSocketDisconnect:
        manager.disconnect(websocket)

"""주문/체결 WebSocket 게이트웨이"""
import asyncio
import json
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
_order_connections: Set[WebSocket] = set()


async def broadcast_order_update(order_data: dict):
    if not _order_connections:
        return
    message = json.dumps(order_data, ensure_ascii=False, default=str)
    disconnected = set()
    for ws in _order_connections.copy():
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    _order_connections.difference_update(disconnected)


@router.websocket("/ws/orders")
async def order_websocket(websocket: WebSocket):
    await websocket.accept()
    _order_connections.add(websocket)
    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        _order_connections.discard(websocket)

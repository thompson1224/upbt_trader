"""AI 신호 WebSocket 게이트웨이"""
import asyncio
import json
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
_signal_connections: Set[WebSocket] = set()


async def broadcast_signal(signal_data: dict):
    """새 AI 신호를 모든 클라이언트에 브로드캐스트."""
    if not _signal_connections:
        return
    message = json.dumps(signal_data, ensure_ascii=False, default=str)
    disconnected = set()
    for ws in _signal_connections.copy():
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    _signal_connections.difference_update(disconnected)


@router.websocket("/ws/signals")
async def signal_websocket(websocket: WebSocket):
    await websocket.accept()
    _signal_connections.add(websocket)
    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        _signal_connections.discard(websocket)

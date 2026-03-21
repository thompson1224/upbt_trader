"""실시간 시세 WebSocket 게이트웨이"""
import asyncio
import json
import logging
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

logger = logging.getLogger(__name__)
router = APIRouter()

# 연결된 클라이언트 관리
_connections: Set[WebSocket] = set()
_market_data: dict = {}  # 최신 시세 캐시


async def broadcast(data: dict):
    """모든 연결된 클라이언트에 브로드캐스트."""
    if not _connections:
        return
    message = json.dumps(data, ensure_ascii=False)
    disconnected = set()
    for ws in _connections.copy():
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    _connections.difference_update(disconnected)


@router.websocket("/ws/market")
async def market_websocket(
    websocket: WebSocket,
    codes: str = Query("KRW-BTC,KRW-ETH"),  # 구독할 마켓 코드 (쉼표 구분)
):
    await websocket.accept()
    _connections.add(websocket)
    requested_codes = {c.strip().upper() for c in codes.split(",")}

    # 최신 캐시 먼저 전송
    for code, data in _market_data.items():
        if code in requested_codes:
            await websocket.send_text(json.dumps(data, ensure_ascii=False))

    try:
        while True:
            # 클라이언트 연결 유지 (ping 처리)
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if msg == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        _connections.discard(websocket)

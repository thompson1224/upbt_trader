"""실시간 시세 WebSocket 게이트웨이"""
import asyncio
import json
import logging
import os
from typing import Set

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

logger = logging.getLogger(__name__)
router = APIRouter()

# 연결된 클라이언트 관리
_connections: Set[WebSocket] = set()
_market_data: dict = {}  # 최신 시세 캐시


async def start_redis_subscriber():
    """Redis pub/sub에서 ticker 수신 → WS 브로드캐스트."""
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    while True:
        try:
            r = aioredis.from_url(redis_url)
            pubsub = r.pubsub()
            await pubsub.subscribe("upbit:ticker")
            logger.info("Market WS: Redis subscriber connected")
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        market = data.get("cd", "")
                        if market:
                            _market_data[market] = data
                            await broadcast(data)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("Market Redis subscriber error: %s, retrying in 3s", e)
            await asyncio.sleep(3)


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

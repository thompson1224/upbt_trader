"""AI 신호 WebSocket 게이트웨이"""
import asyncio
import json
import logging
import os
from typing import Set

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()
_signal_connections: Set[WebSocket] = set()


async def start_redis_subscriber():
    """Redis pub/sub에서 신호 수신 → WS 브로드캐스트."""
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    r = None
    try:
        while True:
            try:
                r = aioredis.from_url(redis_url)
                pubsub = r.pubsub()
                await pubsub.subscribe("upbit:signal")
                logger.info("Signal WS: Redis subscriber connected")
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        try:
                            data = json.loads(message["data"])
                            await broadcast_signal(data)
                        except Exception:
                            pass
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("Signal Redis subscriber error: %s, retrying in 3s", e)
                if r:
                    await r.aclose()
                    r = None
                await asyncio.sleep(3)
    finally:
        if r:
            await r.aclose()


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

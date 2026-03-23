"""Trade Event & Position Update WebSocket 게이트웨이"""
import asyncio
import json
import logging
import os
from typing import Set

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()

_trade_connections: Set[WebSocket] = set()
_portfolio_connections: Set[WebSocket] = set()


async def _broadcast(connections: Set[WebSocket], data: dict):
    if not connections:
        return
    message = json.dumps(data, ensure_ascii=False)
    disconnected = set()
    for ws in connections.copy():
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    connections.difference_update(disconnected)


async def start_trade_event_subscriber():
    """Redis upbit:trade_event → /ws/trade-events 브로드캐스트."""
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    while True:
        try:
            r = aioredis.from_url(redis_url)
            pubsub = r.pubsub()
            await pubsub.subscribe("upbit:trade_event")
            logger.info("Trade Event WS: Redis subscriber connected")
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        await _broadcast(_trade_connections, data)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("Trade Event Redis subscriber error: %s, retrying in 3s", e)
            await asyncio.sleep(3)


async def start_portfolio_subscriber():
    """Redis upbit:position_update → /ws/portfolio 브로드캐스트."""
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    while True:
        try:
            r = aioredis.from_url(redis_url)
            pubsub = r.pubsub()
            await pubsub.subscribe("upbit:position_update")
            logger.info("Portfolio WS: Redis subscriber connected")
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        await _broadcast(_portfolio_connections, data)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("Portfolio Redis subscriber error: %s, retrying in 3s", e)
            await asyncio.sleep(3)


@router.websocket("/ws/trade-events")
async def trade_events_websocket(websocket: WebSocket):
    await websocket.accept()
    _trade_connections.add(websocket)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if msg == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        _trade_connections.discard(websocket)


@router.websocket("/ws/portfolio")
async def portfolio_websocket(websocket: WebSocket):
    await websocket.accept()
    _portfolio_connections.add(websocket)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if msg == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        _portfolio_connections.discard(websocket)

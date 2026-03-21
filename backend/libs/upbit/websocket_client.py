from __future__ import annotations
"""Upbit WebSocket Client - 재연결 + Ping/Pong + 백프레셔 제어"""
import asyncio
import json
import logging
import uuid
from typing import Callable, Awaitable
from datetime import datetime

import websockets
from tenacity import retry, wait_exponential, stop_never, before_sleep_log

from libs.config import get_settings

logger = logging.getLogger(__name__)

UPBIT_WS_URL = "wss://api.upbit.com/websocket/v1"

MessageHandler = Callable[[dict], Awaitable[None]]


class UpbitWebSocketClient:
    """
    업비트 Public WebSocket 클라이언트.
    - ticker/trade/orderbook 구독
    - 자동 재연결 (exponential backoff)
    - 120초 유휴 방지용 Ping 전송
    """

    def __init__(
        self,
        markets: list[str],
        types: list[str],  # ["ticker", "trade", "orderbook"]
        on_message: MessageHandler,
        ping_interval: float | None = None,
    ):
        self.markets = markets
        self.types = types
        self.on_message = on_message
        settings = get_settings()
        self.ping_interval = ping_interval or settings.ws_ping_interval_sec
        self._running = False
        self._ws = None

    def _build_subscribe_payload(self) -> str:
        ticket = [{"ticket": str(uuid.uuid4())}]
        type_entries = [
            {"type": t, "codes": self.markets, "isOnlyRealtime": True}
            for t in self.types
        ]
        fmt = [{"format": "SIMPLE"}]
        return json.dumps(ticket + type_entries + fmt)

    @retry(
        wait=wait_exponential(
            multiplier=1,
            min=get_settings().ws_reconnect_min_sec,
            max=get_settings().ws_reconnect_max_sec,
        ),
        stop=stop_never,
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=False,
    )
    async def _connect_and_run(self):
        payload = self._build_subscribe_payload()
        async with websockets.connect(
            UPBIT_WS_URL,
            ping_interval=None,  # 직접 ping 관리
            close_timeout=5,
        ) as ws:
            self._ws = ws
            await ws.send(payload)
            logger.info("Upbit WS connected. markets=%d, types=%s", len(self.markets), self.types)

            ping_task = asyncio.create_task(self._ping_loop(ws))
            try:
                async for raw in ws:
                    if not self._running:
                        break
                    try:
                        data = json.loads(raw)
                        await self.on_message(data)
                    except Exception as e:
                        logger.warning("Message handler error: %s", e)
            finally:
                ping_task.cancel()
                self._ws = None

    async def _ping_loop(self, ws):
        """업비트 120초 유휴 연결 끊김 방지."""
        while True:
            await asyncio.sleep(self.ping_interval)
            try:
                await ws.send("PING")
            except Exception:
                break

    async def start(self):
        self._running = True
        await self._connect_and_run()

    async def stop(self):
        self._running = False
        if self._ws:
            await self._ws.close()

    def update_markets(self, markets: list[str]):
        """마켓 목록 갱신 (재구독은 재연결 시 적용)."""
        self.markets = markets

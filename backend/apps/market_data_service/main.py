from __future__ import annotations
"""시장 데이터 수집 서비스 - Upbit WS 구독 + DB 적재"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import redis.asyncio as aioredis
from libs.config import get_settings
from libs.upbit.websocket_client import UpbitWebSocketClient
from libs.upbit.rest_client import UpbitRestClient
from libs.db.session import get_session_factory
from libs.db.models import Coin, Candle1m
from sqlalchemy import select, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_candle_buffer: dict[str, list] = {}  # market -> [tick]
_redis: aioredis.Redis | None = None


async def on_tick(data: dict):
    """WebSocket 티커 수신 핸들러."""
    if data.get("ty") != "ticker":
        return

    market = data.get("cd", "")
    if not market:
        return

    # Redis로 실시간 ticker 전달
    if _redis:
        try:
            await _redis.publish("upbit:ticker", json.dumps(data))
        except Exception:
            pass

    # 1분봉 누적
    ts = datetime.fromtimestamp(data.get("tms", 0) / 1000, tz=timezone.utc)
    minute_key = ts.strftime("%Y-%m-%dT%H:%M")

    if market not in _candle_buffer:
        _candle_buffer[market] = []

    _candle_buffer[market].append({
        "ts": ts,
        "trade_price": data.get("tp", 0),
        "trade_volume": data.get("tv", 0),
        "minute_key": minute_key,
    })

    # 주기적 플러시는 별도 태스크에서 처리


async def flush_candles_loop():
    """1분마다 누적 틱을 1분봉으로 집계 후 DB 저장."""
    session_factory = get_session_factory()
    while True:
        await asyncio.sleep(60)
        if not _candle_buffer:
            continue

        buffer_snapshot = {k: v[:] for k, v in _candle_buffer.items()}
        _candle_buffer.clear()

        async with session_factory() as db:
            for market, ticks in buffer_snapshot.items():
                if not ticks:
                    continue

                # 코인 ID 조회
                result = await db.execute(
                    select(Coin.id).where(Coin.market == market)
                )
                coin_id = result.scalar_one_or_none()
                if not coin_id:
                    continue

                # 1분봉 집계
                prices = [t["trade_price"] for t in ticks]
                volumes = [t["trade_volume"] for t in ticks]
                candle_ts = ticks[0]["ts"].replace(second=0, microsecond=0)

                stmt = pg_insert(Candle1m).values(
                    coin_id=coin_id,
                    ts=candle_ts,
                    open=prices[0],
                    high=max(prices),
                    low=min(prices),
                    close=prices[-1],
                    volume=sum(volumes),
                    value=sum(p * v for p, v in zip(prices, volumes)),
                ).on_conflict_do_update(
                    constraint="uq_candles_1m_coin_ts",
                    set_={
                        "close": prices[-1],
                        "high": max(prices),
                        "low": min(prices),
                        "volume": sum(volumes),
                        "value": sum(p * v for p, v in zip(prices, volumes)),
                    },
                )
                await db.execute(stmt)

            await db.commit()
            logger.info("Flushed candles for %d markets", len(buffer_snapshot))


async def sync_krw_markets():
    """KRW 마켓 목록 동기화 (시작 시 + 주기적)."""
    rest = UpbitRestClient()
    session_factory = get_session_factory()

    markets = await rest.get_krw_markets()
    async with session_factory() as db:
        for m in markets:
            market_code = m.get("market", "")
            if not market_code.startswith("KRW-"):
                continue
            parts = market_code.split("-")
            base = parts[1] if len(parts) > 1 else market_code

            stmt = pg_insert(Coin).values(
                market=market_code,
                base_currency=base,
                quote_currency="KRW",
                is_active=True,
                market_warning="CAUTION" if m.get("market_event", {}).get("caution") else None,
            ).on_conflict_do_update(
                index_elements=["market"],
                set_={"is_active": True},
            )
            await db.execute(stmt)
        await db.commit()
    logger.info("Synced %d KRW markets", len(markets))
    return [m["market"] for m in markets if m.get("market", "").startswith("KRW-")]


async def main():
    global _redis
    settings = get_settings()
    logger.info("Starting market data service...")

    # Redis 연결
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    _redis = aioredis.from_url(redis_url)

    # 마켓 동기화
    markets = await sync_krw_markets()
    logger.info("Subscribing to %d markets", len(markets))

    # WebSocket 수집 + 플러시 루프 병렬 실행
    ws_client = UpbitWebSocketClient(
        markets=markets,
        types=["ticker"],
        on_message=on_tick,
    )

    await asyncio.gather(
        ws_client.start(),
        flush_candles_loop(),
    )


if __name__ == "__main__":
    asyncio.run(main())

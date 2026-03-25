from __future__ import annotations
"""마켓 API"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json
import os
import redis.asyncio as aioredis

from libs.db.session import get_db
from libs.db.models import Coin, Candle1m
from schemas.market import CoinResponse, CandleResponse

router = APIRouter()
EXCLUDED_MARKETS_REDIS_KEY = "settings:excluded_markets"


def _get_redis():
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    return aioredis.from_url(redis_url)


@router.get("/markets", response_model=list[CoinResponse])
async def get_markets(
    active_only: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    """KRW 마켓 목록 조회."""
    stmt = select(Coin)
    if active_only:
        stmt = stmt.where(Coin.is_active == True)
    stmt = stmt.order_by(Coin.market)
    result = await db.execute(stmt)
    markets = result.scalars().all()

    r = _get_redis()
    try:
        raw = await r.get(EXCLUDED_MARKETS_REDIS_KEY)
    finally:
        await r.aclose()
    excluded_reason_map: dict[str, str] = {}
    if raw is not None:
        payload = json.loads(raw.decode())
        if isinstance(payload, list):
            excluded_reason_map = {market: "" for market in payload}
        elif isinstance(payload, dict):
            excluded_reason_map = {
                str(item.get("market", "")).upper(): str(item.get("reason", "") or "")
                for item in payload.get("items", [])
                if str(item.get("market", "")).strip()
            }
    excluded = set(excluded_reason_map.keys())

    return [
        CoinResponse.model_validate(coin).model_copy(
            update={
                "excluded": coin.market in excluded,
                "excluded_reason": excluded_reason_map.get(coin.market),
            }
        )
        for coin in markets
    ]


@router.get("/markets/{market}/candles", response_model=list[CandleResponse])
async def get_candles(
    market: str,
    interval: str = Query("1m", regex="^(1m|5m|15m|1h|4h|1d)$"),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """마켓 캔들 데이터 조회."""
    stmt = (
        select(Coin.id)
        .where(Coin.market == market.upper())
    )
    result = await db.execute(stmt)
    coin_id = result.scalar_one_or_none()
    if not coin_id:
        return []

    candle_stmt = (
        select(Candle1m)
        .where(Candle1m.coin_id == coin_id)
        .order_by(Candle1m.ts.desc())
        .limit(limit)
    )
    candles = await db.execute(candle_stmt)
    return list(reversed(candles.scalars().all()))

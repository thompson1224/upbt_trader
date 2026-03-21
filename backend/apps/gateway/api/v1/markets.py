from __future__ import annotations
"""마켓 API"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from libs.db.session import get_db
from libs.db.models import Coin, Candle1m
from schemas.market import CoinResponse, CandleResponse

router = APIRouter()


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
    return result.scalars().all()


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

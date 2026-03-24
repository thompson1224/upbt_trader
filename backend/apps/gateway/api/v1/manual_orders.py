from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional
import os

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.execution_service.main import MANUAL_TEST_STRATEGY_ID
from apps.gateway.api.v1.settings import MANUAL_TEST_MODE_REDIS_KEY
from libs.audit import record_audit_event
from libs.db.models import Coin, Signal
from libs.db.session import get_db
from libs.upbit.rest_client import UpbitRestClient

router = APIRouter()
MIN_MANUAL_TEST_ORDER_KRW = 5_000
MAX_MANUAL_TEST_ORDER_KRW = 10_000


def _get_redis():
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    return aioredis.from_url(redis_url)


async def _is_manual_test_mode_enabled() -> bool:
    r = _get_redis()
    try:
        val = await r.get(MANUAL_TEST_MODE_REDIS_KEY)
    finally:
        await r.aclose()
    return (val is not None) and (val.decode() == "1")


class ManualOrderRequest(BaseModel):
    market: str
    side: Literal["buy", "sell"]
    krw_amount: Optional[float] = None
    volume: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@router.post("/manual-orders")
async def create_manual_order(
    req: ManualOrderRequest,
    db: AsyncSession = Depends(get_db),
):
    if not await _is_manual_test_mode_enabled():
        raise HTTPException(409, "Manual test mode is disabled")

    market = req.market.strip().upper()
    if not market.startswith("KRW-"):
        raise HTTPException(400, "Only KRW markets are supported")

    coin_result = await db.execute(select(Coin).where(Coin.market == market))
    coin = coin_result.scalar_one_or_none()
    if not coin:
        raise HTTPException(404, "Market not found")

    suggested_qty: float | None = None
    upbit = UpbitRestClient()

    if req.side == "buy":
        if req.krw_amount is None:
            raise HTTPException(400, "krw_amount is required for buy orders")
        if req.krw_amount < MIN_MANUAL_TEST_ORDER_KRW:
            raise HTTPException(400, f"Minimum manual test buy is {MIN_MANUAL_TEST_ORDER_KRW} KRW")
        if req.krw_amount > MAX_MANUAL_TEST_ORDER_KRW:
            raise HTTPException(400, f"Maximum manual test buy is {MAX_MANUAL_TEST_ORDER_KRW} KRW")
        entry_price = await upbit.get_ticker(market)
        if not entry_price or entry_price <= 0:
            raise HTTPException(502, "Failed to fetch current price")
        suggested_qty = req.krw_amount / entry_price
    else:
        if req.volume is not None and req.volume <= 0:
            raise HTTPException(400, "volume must be greater than 0")
        suggested_qty = req.volume

    signal = Signal(
        strategy_id=MANUAL_TEST_STRATEGY_ID,
        coin_id=coin.id,
        timeframe="test",
        ts=datetime.now(tz=timezone.utc),
        ta_score=0.0,
        sentiment_score=0.0,
        final_score=1.0,
        confidence=1.0,
        side=req.side,
        status="new",
        suggested_stop_loss=req.stop_loss,
        suggested_take_profit=req.take_profit,
        suggested_qty=suggested_qty,
    )
    db.add(signal)
    await db.flush()

    await record_audit_event(
        event_type="manual_order_requested",
        source="manual_order_api",
        message=f"Manual test order queued: {market} {req.side}",
        market=market,
        payload={
            "signal_id": signal.id,
            "side": req.side,
            "krw_amount": req.krw_amount,
            "volume": req.volume,
            "suggested_qty": suggested_qty,
        },
    )

    return {
        "signalId": signal.id,
        "strategyId": signal.strategy_id,
        "market": market,
        "side": req.side,
        "status": signal.status,
        "krwAmount": req.krw_amount,
        "volume": req.volume,
        "suggestedQty": suggested_qty,
    }

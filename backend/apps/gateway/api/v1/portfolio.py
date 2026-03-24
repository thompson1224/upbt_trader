from __future__ import annotations
import json
import os

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from libs.audit import record_audit_event
from libs.config import get_settings
from libs.db.session import get_db
from libs.db.models import Position, Coin, RuntimeState

router = APIRouter()
PORTFOLIO_EQUITY_CURVE_KEY = "portfolio:equity_curve"
PORTFOLIO_LATEST_SNAPSHOT_KEY = "portfolio:latest_snapshot"
POSITION_SOURCE_STRATEGY = "strategy"
POSITION_SOURCE_EXTERNAL = "external"
POSITION_SOURCE_OVERRIDE_KEY_PREFIX = "position.management."


class PositionAutoTradeRequest(BaseModel):
    enabled: bool


def _get_redis():
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    return aioredis.from_url(redis_url)


def _position_management_key(coin_id: int) -> str:
    return f"{POSITION_SOURCE_OVERRIDE_KEY_PREFIX}{coin_id}"


def _default_protection_levels(
    entry_price: float,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> tuple[float | None, float | None]:
    if entry_price <= 0:
        return None, None
    safe_stop_loss_pct = min(max(stop_loss_pct, 0.0), 0.99)
    safe_take_profit_pct = max(take_profit_pct, 0.0)
    return (
        entry_price * (1 - safe_stop_loss_pct),
        entry_price * (1 + safe_take_profit_pct),
    )


@router.get("/positions")
async def get_positions(db: AsyncSession = Depends(get_db)):
    stmt = select(Position, Coin.market).join(Coin)
    result = await db.execute(stmt)
    rows = result.all()
    return [
        {
            "id": pos.id,
            "market": market,
            "qty": pos.qty,
            "avg_entry_price": pos.avg_entry_price,
            "unrealized_pnl": pos.unrealized_pnl,
            "realized_pnl": pos.realized_pnl,
            "source": pos.source,
            "stop_loss": pos.stop_loss,
            "take_profit": pos.take_profit,
        }
        for pos, market in rows
        if pos.qty > 0
    ]


@router.patch("/positions/{market}/auto-trade")
async def set_position_auto_trade(
    market: str,
    req: PositionAutoTradeRequest,
    db: AsyncSession = Depends(get_db),
):
    normalized_market = market.upper()
    coin_result = await db.execute(select(Coin).where(Coin.market == normalized_market))
    coin = coin_result.scalar_one_or_none()
    if coin is None:
        raise HTTPException(status_code=404, detail="Market not found")

    position_result = await db.execute(select(Position).where(Position.coin_id == coin.id))
    position = position_result.scalar_one_or_none()
    if position is None or position.qty <= 0:
        raise HTTPException(status_code=404, detail="Open position not found")

    override_key = _position_management_key(coin.id)
    runtime_state = await db.get(RuntimeState, override_key)
    target_source = POSITION_SOURCE_STRATEGY if req.enabled else POSITION_SOURCE_EXTERNAL

    if runtime_state is None:
        db.add(RuntimeState(key=override_key, value=target_source))
    else:
        runtime_state.value = target_source

    position.source = target_source
    if req.enabled:
        settings = get_settings()
        stop_loss, take_profit = _default_protection_levels(
            position.avg_entry_price,
            settings.risk_default_stop_loss_pct,
            settings.risk_default_take_profit_pct,
        )
        position.stop_loss = stop_loss
        position.take_profit = take_profit
    else:
        position.stop_loss = None
        position.take_profit = None

    await db.commit()
    await db.refresh(position)

    await record_audit_event(
        event_type="position_auto_trade_toggled",
        source="portfolio",
        market=normalized_market,
        message=f"Position {normalized_market} {'included in' if req.enabled else 'excluded from'} auto-trade",
        payload={
            "enabled": req.enabled,
            "coin_id": coin.id,
            "position_id": position.id,
        },
    )

    return {
        "id": position.id,
        "market": normalized_market,
        "qty": position.qty,
        "avg_entry_price": position.avg_entry_price,
        "source": position.source,
        "stop_loss": position.stop_loss,
        "take_profit": position.take_profit,
        "auto_trade_managed": position.source == POSITION_SOURCE_STRATEGY,
    }


@router.get("/portfolio/equity-curve")
async def get_equity_curve(limit: int = Query(100, ge=1, le=500)):
    r = _get_redis()
    try:
        items = await r.lrange(PORTFOLIO_EQUITY_CURVE_KEY, -limit, -1)
        latest = await r.get(PORTFOLIO_LATEST_SNAPSHOT_KEY)
    finally:
        await r.aclose()

    data = [json.loads(item) for item in items]
    latest_data = json.loads(latest) if latest else (data[-1] if data else None)
    return {"data": data, "latest": latest_data}

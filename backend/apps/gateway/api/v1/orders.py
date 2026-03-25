from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from libs.db.session import get_db
from libs.db.models import Order, Coin

router = APIRouter()

_SIDE_MAP = {"bid": "buy", "ask": "sell"}


@router.get("/orders")
async def get_orders(
    state: Optional[str] = None,
    market: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Order, Coin.market)
        .join(Coin, Order.coin_id == Coin.id)
    )
    if state:
        stmt = stmt.where(Order.state == state)
    if market:
        stmt = stmt.where(Coin.market == market.upper())
    stmt = stmt.order_by(Order.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    rows = result.all()
    return [
        {
            "id": o.id,
            "market": market,
            "side": _SIDE_MAP.get(o.side, o.side),
            "status": o.state,
            "ordType": o.ord_type,
            "price": o.price,
            "volume": o.volume or 0,
            "ts": o.created_at.isoformat() if o.created_at else None,
        }
        for o, market in rows
    ]

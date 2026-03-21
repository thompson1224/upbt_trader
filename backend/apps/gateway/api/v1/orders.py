from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from libs.db.session import get_db
from libs.db.models import Order

router = APIRouter()


@router.get("/orders")
async def get_orders(
    state: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Order)
    if state:
        stmt = stmt.where(Order.state == state)
    stmt = stmt.order_by(Order.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    orders = result.scalars().all()
    return [
        {
            "id": o.id,
            "coin_id": o.coin_id,
            "exchange_order_id": o.exchange_order_id,
            "side": o.side,
            "ord_type": o.ord_type,
            "price": o.price,
            "volume": o.volume,
            "state": o.state,
            "created_at": o.created_at,
        }
        for o in orders
    ]

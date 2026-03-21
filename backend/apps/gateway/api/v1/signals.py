from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from libs.db.session import get_db
from libs.db.models import Signal, Coin
from schemas.signal import SignalResponse

router = APIRouter()


@router.get("/signals", response_model=List[SignalResponse])
async def get_signals(
    market: Optional[str] = Query(None),
    side: Optional[str] = Query(None, regex="^(buy|sell|hold)$"),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Signal).join(Coin)
    if market:
        stmt = stmt.where(Coin.market == market.upper())
    if side:
        stmt = stmt.where(Signal.side == side)
    stmt = stmt.order_by(Signal.ts.desc()).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()

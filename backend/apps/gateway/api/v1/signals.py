from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from libs.db.session import get_db
from libs.db.models import Signal, Coin
from schemas.signal import SignalResponse

router = APIRouter()


@router.get("/signals", response_model=List[SignalResponse])
async def get_signals(
    market: Optional[str] = Query(None),
    side: Optional[str] = Query(None, pattern="^(buy|sell|hold)$"),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Signal, Coin.market.label("coin_market"))
        .join(Coin, Signal.coin_id == Coin.id)
    )
    if market:
        stmt = stmt.where(Coin.market == market.upper())
    if side:
        stmt = stmt.where(Signal.side == side)
    stmt = stmt.order_by(Signal.ts.desc()).limit(limit)
    result = await db.execute(stmt)
    rows = result.all()

    signals = []
    for sig, coin_market in rows:
        data = SignalResponse.model_validate(sig)
        data.market = coin_market
        signals.append(data)
    return signals

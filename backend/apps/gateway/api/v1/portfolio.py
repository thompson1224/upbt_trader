from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from libs.db.session import get_db
from libs.db.models import Position, Coin

router = APIRouter()


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
            "stop_loss": pos.stop_loss,
            "take_profit": pos.take_profit,
        }
        for pos, market in rows
        if pos.qty > 0
    ]


@router.get("/portfolio/equity-curve")
async def get_equity_curve():
    # TODO: Redis에서 실시간 자산 곡선 데이터 반환
    return {"data": [], "message": "Coming soon"}

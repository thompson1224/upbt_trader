from decimal import Decimal
from typing import Optional
import sqlalchemy as sa
from sqlalchemy import Boolean, Integer, Numeric, ForeignKey, String
from sqlalchemy.orm import mapped_column, Mapped, relationship
from .base import Base, TimestampMixin

_PRICE_COL = Numeric(20, 8)


class Position(Base, TimestampMixin):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    coin_id: Mapped[int] = mapped_column(ForeignKey("coins.id"), unique=True, nullable=False)

    qty: Mapped[Decimal] = mapped_column(_PRICE_COL, nullable=False, default=Decimal("0"))
    avg_entry_price: Mapped[Decimal] = mapped_column(_PRICE_COL, nullable=False, default=Decimal("0"))
    unrealized_pnl: Mapped[Decimal] = mapped_column(_PRICE_COL, nullable=False, default=Decimal("0"))
    realized_pnl: Mapped[Decimal] = mapped_column(_PRICE_COL, nullable=False, default=Decimal("0"))
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="external")

    stop_loss: Mapped[Optional[Decimal]] = mapped_column(_PRICE_COL, nullable=True)
    take_profit: Mapped[Optional[Decimal]] = mapped_column(_PRICE_COL, nullable=True)
    # SL/TP 중복 청산 방지: True이면 청산 진행 중 (atomic claim)
    liquidating: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa.false()
    )

    coin = relationship("Coin", back_populates="positions")

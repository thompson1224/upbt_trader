from typing import Optional
from sqlalchemy import Integer, Float, ForeignKey, String
from sqlalchemy.orm import mapped_column, Mapped, relationship
from .base import Base, TimestampMixin


class Position(Base, TimestampMixin):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    coin_id: Mapped[int] = mapped_column(ForeignKey("coins.id"), unique=True, nullable=False)

    qty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_entry_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="external")

    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    coin = relationship("Coin", back_populates="positions")

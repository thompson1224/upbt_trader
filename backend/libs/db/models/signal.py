from sqlalchemy import Integer, Float, String, DateTime, ForeignKey, Index
from sqlalchemy.orm import mapped_column, Mapped, relationship
from datetime import datetime
from typing import Literal, Optional
from .base import Base


SignalSide = Literal["buy", "sell", "hold"]
SignalStatus = Literal["new", "approved", "rejected", "executed", "expired"]


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        Index("ix_signal_strategy_ts", "strategy_id", "ts"),
        Index("ix_signal_coin_ts", "coin_id", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(String(50), nullable=False)
    coin_id: Mapped[int] = mapped_column(ForeignKey("coins.id"), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(5), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Scores
    ta_score: Mapped[float] = mapped_column(Float, nullable=False)
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    final_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    # Decision
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # buy/sell/hold
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")

    # Risk
    suggested_stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    suggested_take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    suggested_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    rejection_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    coin = relationship("Coin", back_populates="signals")
    orders = relationship("Order", back_populates="signal")

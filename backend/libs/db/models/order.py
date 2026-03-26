from typing import Optional
from sqlalchemy import Integer, Float, String, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import mapped_column, Mapped, relationship
from datetime import datetime
from .base import Base, TimestampMixin


class Order(Base, TimestampMixin):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_state_ts", "state", "created_at"),
        UniqueConstraint("signal_id", name="uq_orders_signal_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("signals.id"), nullable=True)
    coin_id: Mapped[int] = mapped_column(ForeignKey("coins.id"), nullable=False)

    exchange_order_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True, nullable=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # bid/ask
    ord_type: Mapped[str] = mapped_column(String(20), nullable=False)  # limit/price/market
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="wait")
    # wait, watch, done, cancel

    rejected_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    signal = relationship("Signal", back_populates="orders")
    fills = relationship("Fill", back_populates="order")


class Fill(Base):
    __tablename__ = "fills"
    __table_args__ = (
        Index("ix_fills_order_ts", "order_id", "filled_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    trade_uuid: Mapped[str] = mapped_column(String(100), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    fee: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    order = relationship("Order", back_populates="fills")

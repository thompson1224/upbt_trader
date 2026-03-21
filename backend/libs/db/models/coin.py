from typing import Optional
from sqlalchemy import String, Boolean
from sqlalchemy.orm import mapped_column, Mapped, relationship
from .base import Base, TimestampMixin


class Coin(Base, TimestampMixin):
    __tablename__ = "coins"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    base_currency: Mapped[str] = mapped_column(String(10), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(10), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    market_warning: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    candles = relationship("Candle1m", back_populates="coin", lazy="dynamic")
    signals = relationship("Signal", back_populates="coin", lazy="dynamic")
    positions = relationship("Position", back_populates="coin")

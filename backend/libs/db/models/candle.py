from sqlalchemy import Integer, Float, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import mapped_column, Mapped, relationship
from datetime import datetime
from .base import Base


class Candle1m(Base):
    __tablename__ = "candles_1m"
    __table_args__ = (
        UniqueConstraint("coin_id", "ts", name="uq_candles_1m_coin_ts"),
        Index("ix_candles_1m_coin_ts_desc", "coin_id", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    coin_id: Mapped[int] = mapped_column(ForeignKey("coins.id"), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)  # 거래대금

    coin = relationship("Coin", back_populates="candles")

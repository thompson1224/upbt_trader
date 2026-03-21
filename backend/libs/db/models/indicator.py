from typing import Optional
from sqlalchemy import Integer, Float, String, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import mapped_column, Mapped
from datetime import datetime
from .base import Base


class IndicatorSnapshot(Base):
    __tablename__ = "indicator_snapshots"
    __table_args__ = (
        UniqueConstraint("coin_id", "timeframe", "ts", name="uq_indicator_coin_tf_ts"),
        Index("ix_indicator_coin_ts", "coin_id", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    coin_id: Mapped[int] = mapped_column(ForeignKey("coins.id"), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(5), nullable=False)  # 1m, 5m, 15m
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # RSI
    rsi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # MACD
    macd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_signal: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_hist: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Bollinger Bands
    bb_upper: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_mid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_lower: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # %B

    # Moving Averages
    ema_20: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ema_50: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # TA Score (-1 ~ 1)
    ta_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

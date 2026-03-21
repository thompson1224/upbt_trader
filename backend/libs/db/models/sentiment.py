from typing import Optional
from sqlalchemy import Integer, Float, String, DateTime, ForeignKey, Text, Index
from sqlalchemy.orm import mapped_column, Mapped
from datetime import datetime
from .base import Base


class SentimentSnapshot(Base):
    __tablename__ = "sentiment_snapshots"
    __table_args__ = (
        Index("ix_sentiment_coin_ts", "coin_id", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    coin_id: Mapped[int] = mapped_column(ForeignKey("coins.id"), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # claude, news, etc.

    sentiment_score: Mapped[float] = mapped_column(Float, nullable=False)  # -1 ~ 1
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0 ~ 1
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)

    # Claude 분석 결과
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    keywords: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array string
    raw_prompt_ref: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

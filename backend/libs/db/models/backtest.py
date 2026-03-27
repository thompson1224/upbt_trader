from typing import Optional
from sqlalchemy import Integer, Float, String, DateTime, ForeignKey, Text, Index
from sqlalchemy.orm import mapped_column, Mapped, relationship
from datetime import datetime
from .base import Base, TimestampMixin


class BacktestRun(Base, TimestampMixin):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(String(50), nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)

    train_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    train_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    test_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    test_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # pending, running, completed, failed
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    trades = relationship("BacktestTrade", back_populates="run")
    metrics = relationship("BacktestMetrics", back_populates="run", uselist=False)
    windows = relationship("BacktestWindow", back_populates="run")


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"
    __table_args__ = (
        Index("ix_backtest_trades_run_coin", "run_id", "coin_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), nullable=False)
    coin_id: Mapped[int] = mapped_column(ForeignKey("coins.id"), nullable=False)

    entry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_ts: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fee: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    slippage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    run = relationship("BacktestRun", back_populates="trades")


class BacktestMetrics(Base):
    __tablename__ = "backtest_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), unique=True, nullable=False)

    cagr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    win_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_trades: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    turnover: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    run = relationship("BacktestRun", back_populates="metrics")


class BacktestWindow(Base):
    __tablename__ = "backtest_windows"
    __table_args__ = (
        Index("ix_backtest_windows_run_seq", "run_id", "window_seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), nullable=False)
    window_seq: Mapped[int] = mapped_column(Integer, nullable=False)

    train_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    train_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    test_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    test_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    start_equity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    end_equity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    net_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    cagr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    win_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_trades: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    run = relationship("BacktestRun", back_populates="windows")

from __future__ import annotations
from typing import Optional
"""이벤트 기반 백테스팅 엔진 - Walk-forward 지원"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable
import numpy as np
import pandas as pd

from apps.strategy_service.indicators.calculator import compute_indicators
from apps.strategy_service.fusion.signal_fusion import fuse_signals


@dataclass
class BacktestConfig:
    market: str
    strategy_id: str
    fee_bps: float = 5.0        # 거래 수수료 (basis points)
    slippage_bps: float = 3.0   # 슬리피지
    initial_equity: float = 1_000_000.0  # 초기 자산 (KRW)
    stop_loss_pct: float = 0.03  # 손절 3%
    take_profit_pct: float = 0.06  # 익절 6%
    ta_weight: float = 0.6
    sentiment_weight: float = 0.4


@dataclass
class Trade:
    market: str
    entry_ts: datetime
    entry_price: float
    qty: float
    exit_ts: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    fee: float = 0.0
    slippage: float = 0.0


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: list[dict]  # [{ts, equity}]
    cagr: float
    sharpe: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    total_trades: int


class BacktestEngine:
    """이벤트 기반 백테스팅 엔진."""

    def __init__(self, config: BacktestConfig):
        self.config = config

    def run(self, candles_df: pd.DataFrame) -> BacktestResult:
        """
        캔들 데이터로 백테스트 실행.
        candles_df: columns=[ts, open, high, low, close, volume, value]
        """
        cfg = self.config
        equity = cfg.initial_equity
        position_qty = 0.0
        position_entry_price = 0.0
        position_stop = 0.0
        position_take_profit = 0.0

        trades: list[Trade] = []
        equity_curve: list[dict] = []
        current_trade: Trade | None = None

        fee_rate = cfg.fee_bps / 10_000
        slippage_rate = cfg.slippage_bps / 10_000

        for i in range(50, len(candles_df)):
            window = candles_df.iloc[:i + 1]
            row = candles_df.iloc[i]
            ts = row["ts"]
            close = float(row["close"])
            high = float(row["high"])
            low = float(row["low"])

            # 지표 계산
            ind = compute_indicators(window)

            # 포지션 중 손절/익절 체크
            if position_qty > 0 and current_trade is not None:
                if low <= position_stop:
                    # 손절
                    exit_price = position_stop * (1 - slippage_rate)
                    pnl = (exit_price - position_entry_price) * position_qty
                    fee = exit_price * position_qty * fee_rate
                    current_trade.exit_ts = ts
                    current_trade.exit_price = exit_price
                    current_trade.pnl = pnl - current_trade.fee - fee
                    current_trade.fee += fee
                    trades.append(current_trade)
                    equity += position_qty * exit_price - fee
                    position_qty = 0.0
                    current_trade = None
                    equity_curve.append({"ts": ts, "equity": equity})
                    continue

                if high >= position_take_profit:
                    # 익절
                    exit_price = position_take_profit * (1 - slippage_rate)
                    pnl = (exit_price - position_entry_price) * position_qty
                    fee = exit_price * position_qty * fee_rate
                    current_trade.exit_ts = ts
                    current_trade.exit_price = exit_price
                    current_trade.pnl = pnl - current_trade.fee - fee
                    current_trade.fee += fee
                    trades.append(current_trade)
                    equity += position_qty * exit_price - fee
                    position_qty = 0.0
                    current_trade = None
                    equity_curve.append({"ts": ts, "equity": equity})
                    continue

            # 신호 생성 (백테스트는 TA-only)
            signal = fuse_signals(ta_score=ind.ta_score)

            # 진입 신호
            if signal.side == "buy" and position_qty == 0:
                entry_price = close * (1 + slippage_rate)
                stop_loss = entry_price * (1 - cfg.stop_loss_pct)
                take_profit = entry_price * (1 + cfg.take_profit_pct)
                risk_budget = equity * 0.01  # 1% 위험
                risk_qty = risk_budget / max(entry_price - stop_loss, 1e-12)
                max_position_qty = (equity * 0.1) / entry_price
                qty = min(risk_qty, max_position_qty)
                order_value = qty * entry_price

                if order_value >= 5_000 and order_value + (entry_price * qty * fee_rate) <= equity:
                    fee = entry_price * qty * fee_rate
                    equity -= order_value + fee
                    position_qty = qty
                    position_entry_price = entry_price
                    position_stop = stop_loss
                    position_take_profit = take_profit
                    current_trade = Trade(
                        market=cfg.market,
                        entry_ts=ts,
                        entry_price=entry_price,
                        qty=qty,
                        fee=fee,
                    )

            elif signal.side == "sell" and position_qty > 0 and current_trade is not None:
                exit_price = close * (1 - slippage_rate)
                pnl = (exit_price - position_entry_price) * position_qty
                fee = exit_price * position_qty * fee_rate
                current_trade.exit_ts = ts
                current_trade.exit_price = exit_price
                current_trade.pnl = pnl - current_trade.fee - fee
                current_trade.fee += fee
                trades.append(current_trade)
                equity += position_qty * exit_price - fee
                position_qty = 0.0
                current_trade = None

            # 포지션 가치 포함 자산 계산
            current_equity = equity + (position_qty * close if position_qty > 0 else 0)
            equity_curve.append({"ts": ts, "equity": current_equity})

        return self._compute_metrics(trades, equity_curve, cfg.initial_equity)

    def _compute_metrics(
        self,
        trades: list[Trade],
        equity_curve: list[dict],
        initial_equity: float,
    ) -> BacktestResult:
        if not equity_curve:
            return BacktestResult(
                trades=trades, equity_curve=[],
                cagr=0, sharpe=0, max_drawdown=0,
                win_rate=0, profit_factor=0, total_trades=0,
            )

        equities = [e["equity"] for e in equity_curve]
        returns = pd.Series(equities).pct_change().dropna()

        # CAGR (일수 기반 단순 계산)
        total_return = equities[-1] / initial_equity - 1
        n_days = max(len(equity_curve) / 1440, 1)  # 1m 캔들 기준
        cagr = (1 + total_return) ** (365 / n_days) - 1

        # Sharpe (연율화, 무위험이자율 3%)
        rf_daily = 0.03 / 365
        excess_returns = returns - rf_daily
        std = float(excess_returns.std())
        sharpe = (excess_returns.mean() / std * np.sqrt(365)) if (len(excess_returns) > 1 and std > 1e-10) else 0.0

        # Max Drawdown
        eq_series = pd.Series(equities)
        rolling_max = eq_series.cummax()
        drawdown = (eq_series - rolling_max) / rolling_max
        max_drawdown = float(drawdown.min())

        # Win Rate & Profit Factor
        completed = [t for t in trades if t.exit_price is not None]
        if completed:
            wins = [t for t in completed if t.pnl > 0]
            losses = [t for t in completed if t.pnl <= 0]
            win_rate = len(wins) / len(completed)
            gross_profit = sum(t.pnl for t in wins)
            gross_loss = abs(sum(t.pnl for t in losses))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        else:
            win_rate = 0.0
            profit_factor = 0.0

        return BacktestResult(
            trades=trades,
            equity_curve=equity_curve,
            cagr=float(cagr),
            sharpe=float(sharpe),
            max_drawdown=float(max_drawdown),
            win_rate=float(win_rate),
            profit_factor=float(profit_factor),
            total_trades=len(completed),
        )

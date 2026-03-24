from types import SimpleNamespace

import pandas as pd
import pytest

from apps.backtest_service.engine.backtest_engine import BacktestConfig, BacktestEngine
from apps.backtest_service.engine import backtest_engine as engine_module


def _make_candles(*, final_low: float = 100.0, final_high: float = 100.0) -> pd.DataFrame:
    rows = []
    start = pd.Timestamp("2026-01-01 00:00:00")
    for i in range(52):
        low = 100.0
        high = 100.0
        if i == 51:
            low = final_low
            high = final_high
        rows.append(
            {
                "ts": start + pd.Timedelta(minutes=i),
                "open": 100.0,
                "high": high,
                "low": low,
                "close": 100.0,
                "volume": 1.0,
                "value": 100.0,
            }
        )
    return pd.DataFrame(rows)


def _force_buy_signal(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        engine_module,
        "compute_indicators",
        lambda window: SimpleNamespace(ta_score=1.0),
    )
    monkeypatch.setattr(
        engine_module,
        "fuse_signals",
        lambda ta_score: SimpleNamespace(
            side="buy",
            ta_score=ta_score,
            sentiment_score=None,
            final_score=ta_score,
            confidence=1.0,
        ),
    )


def test_backtest_stop_loss_restores_proceeds_and_tracks_total_fee(monkeypatch: pytest.MonkeyPatch):
    _force_buy_signal(monkeypatch)

    config = BacktestConfig(market="KRW-BTC", strategy_id="hybrid_v1")
    engine = BacktestEngine(config)
    result = engine.run(_make_candles(final_low=96.9))

    assert result.total_trades == 1
    trade = result.trades[0]

    entry_price = 100.0 * (1 + config.slippage_bps / 10_000)
    qty = (config.initial_equity * 0.1) / entry_price
    entry_fee = entry_price * qty * (config.fee_bps / 10_000)
    exit_price = entry_price * (1 - config.stop_loss_pct) * (1 - config.slippage_bps / 10_000)
    exit_fee = exit_price * qty * (config.fee_bps / 10_000)
    expected_equity = config.initial_equity - (entry_price * qty) - entry_fee + (exit_price * qty) - exit_fee

    assert trade.qty == pytest.approx(qty)
    assert trade.fee == pytest.approx(entry_fee + exit_fee)
    assert trade.pnl == pytest.approx(expected_equity - config.initial_equity)
    assert result.equity_curve[-1]["equity"] == pytest.approx(expected_equity)


def test_backtest_take_profit_uses_capped_position_size(monkeypatch: pytest.MonkeyPatch):
    _force_buy_signal(monkeypatch)

    config = BacktestConfig(market="KRW-ETH", strategy_id="hybrid_v1")
    engine = BacktestEngine(config)
    result = engine.run(_make_candles(final_high=106.1))

    assert result.total_trades == 1
    trade = result.trades[0]

    entry_price = 100.0 * (1 + config.slippage_bps / 10_000)
    capped_qty = (config.initial_equity * 0.1) / entry_price
    assert trade.qty == pytest.approx(capped_qty)
    assert trade.exit_price is not None
    assert trade.exit_price > trade.entry_price

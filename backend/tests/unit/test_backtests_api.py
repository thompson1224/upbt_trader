from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.gateway.api.v1 import backtests as backtests_module


class _FakeScalarResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return list(self.values)

    def scalar_one_or_none(self):
        return self.values[0] if self.values else None


class _FakeRowResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return list(self.rows)


class _FakeSession:
    def __init__(self, *, runs=None, trades=None, windows=None, run_by_id=None):
        self.runs = runs or []
        self.trades = trades or []
        self.windows = windows or []
        self.run_by_id = run_by_id or {}
        self.execute_calls = 0

    async def get(self, _model, run_id):
        return self.run_by_id.get(run_id)

    async def execute(self, _stmt):
        self.execute_calls += 1
        if self.runs and (self.execute_calls == 1 or not self.trades):
            return _FakeScalarResult(self.runs)
        if self.windows:
            return _FakeScalarResult(self.windows)
        return _FakeRowResult(self.trades)


def _make_run(run_id: int, *, status: str = "completed"):
    return SimpleNamespace(
        id=run_id,
        strategy_id="hybrid_v1",
        config_json='{"market":"KRW-BTC","mode":"walk_forward","initial_equity":1000000,"stop_loss_pct":0.03,"take_profit_pct":0.06,"test_window_days":7,"step_days":7}',
        train_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        train_to=datetime(2026, 1, 31, tzinfo=timezone.utc),
        test_from=datetime(2026, 2, 1, tzinfo=timezone.utc),
        test_to=datetime(2026, 2, 28, tzinfo=timezone.utc),
        status=status,
        started_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        finished_at=datetime(2026, 3, 2, tzinfo=timezone.utc),
        error_message=None,
    )


@pytest.mark.asyncio
async def test_get_backtest_run_includes_market_from_config():
    run = _make_run(7)
    fake_db = _FakeSession(run_by_id={7: run})

    response = await backtests_module.get_backtest_run(7, db=fake_db)

    assert response["id"] == 7
    assert response["market"] == "KRW-BTC"
    assert response["initial_equity"] == 1_000_000
    assert response["mode"] == "walk_forward"
    assert response["status"] == "completed"


@pytest.mark.asyncio
async def test_list_backtest_runs_returns_latest_runs():
    runs = [_make_run(3), _make_run(2, status="failed")]
    fake_db = _FakeSession(runs=runs)

    response = await backtests_module.list_backtest_runs(limit=10, db=fake_db)

    assert [row["id"] for row in response] == [3, 2]
    assert response[0]["market"] == "KRW-BTC"
    assert response[1]["status"] == "failed"


def test_build_walk_forward_windows_generates_non_overlapping_segments():
    req = backtests_module.BacktestRunRequest(
        market="KRW-BTC",
        mode="walk_forward",
        train_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        train_to=datetime(2026, 1, 31, tzinfo=timezone.utc),
        test_from=datetime(2026, 2, 1, tzinfo=timezone.utc),
        test_to=datetime(2026, 2, 21, tzinfo=timezone.utc),
        test_window_days=7,
        step_days=7,
    )

    windows = backtests_module._build_walk_forward_windows(req)

    assert len(windows) == 3
    assert windows[0]["window_seq"] == 1
    assert windows[0]["test_from"] == datetime(2026, 2, 1, tzinfo=timezone.utc)
    assert windows[1]["test_from"] == datetime(2026, 2, 8, tzinfo=timezone.utc)
    assert windows[2]["test_to"] == datetime(2026, 2, 21, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_get_backtest_trades_returns_return_pct_and_hold_minutes():
    run = _make_run(5)
    trade = SimpleNamespace(
        id=11,
        entry_ts=datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc),
        exit_ts=datetime(2026, 3, 1, 1, 30, tzinfo=timezone.utc),
        entry_price=100.0,
        exit_price=110.0,
        qty=2.0,
        pnl=18.0,
        fee=2.0,
    )
    fake_db = _FakeSession(run_by_id={5: run}, trades=[(trade, "KRW-ETH")])

    response = await backtests_module.get_backtest_trades(5, db=fake_db)

    assert response[0]["market"] == "KRW-ETH"
    assert response[0]["hold_minutes"] == pytest.approx(90.0)
    assert response[0]["return_pct"] == pytest.approx(0.1)
    assert response[0]["pnl"] == pytest.approx(18.0)


@pytest.mark.asyncio
async def test_get_backtest_trades_raises_when_run_missing():
    fake_db = _FakeSession()

    with pytest.raises(HTTPException) as exc_info:
        await backtests_module.get_backtest_trades(404, db=fake_db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_backtest_windows_returns_serialized_rows():
    run = _make_run(12)
    window = SimpleNamespace(
        id=1,
        window_seq=1,
        train_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        train_to=datetime(2026, 1, 31, tzinfo=timezone.utc),
        test_from=datetime(2026, 2, 1, tzinfo=timezone.utc),
        test_to=datetime(2026, 2, 8, tzinfo=timezone.utc),
        start_equity=1_000_000.0,
        end_equity=1_020_000.0,
        net_pnl=20_000.0,
        cagr=0.12,
        sharpe=1.8,
        max_drawdown=-0.05,
        win_rate=0.6,
        profit_factor=1.4,
        total_trades=5,
    )
    fake_db = _FakeSession(run_by_id={12: run}, windows=[window])

    response = await backtests_module.get_backtest_windows(12, db=fake_db)

    assert response[0]["window_seq"] == 1
    assert response[0]["net_pnl"] == pytest.approx(20_000.0)
    assert response[0]["total_trades"] == 5

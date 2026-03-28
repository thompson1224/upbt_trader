import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from apps.gateway.api.v1 import portfolio as portfolio_module
from libs.db.models import Coin, Position, RuntimeState


class _FakeRedis:
    def __init__(self, items=None, latest=None):
        self.items = items or []
        self.latest = latest
        self.closed = False
        self.values: dict[str, str | bytes] = {}
        self.expirations: dict[str, int | None] = {}

    async def lrange(self, _key, start, end):
        if not self.items:
            return []
        resolved_end = None if end == -1 else end + 1
        return self.items[start:resolved_end]

    async def get(self, key):
        if key in self.values:
            return self.values[key]
        return self.latest

    async def set(self, key, value, ex=None):
        self.values[key] = value
        self.expirations[key] = ex

    async def aclose(self):
        self.closed = True


class _FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeRowsResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def scalars(self):
        class _Scalars:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

            def __iter__(self):
                return iter(self._rows)

        return _Scalars(self.rows)


class _FakeDB:
    def __init__(self, coin: Coin, position: Position):
        self.coin = coin
        self.position = position
        self.runtime_states: dict[str, RuntimeState] = {}
        self.committed = False
        self.refreshed = False
        self.signals = []

    async def execute(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity is Coin:
            return _FakeScalarResult(self.coin)
        if entity is Position:
            return _FakeScalarResult(self.position)
        if entity is portfolio_module.Signal:
            return _FakeRowsResult(self.signals)
        raise AssertionError(f"Unexpected entity: {entity}")

    async def get(self, model, key):
        if model is RuntimeState:
            return self.runtime_states.get(key)
        raise AssertionError(f"Unexpected model: {model}")

    def add(self, instance):
        if isinstance(instance, RuntimeState):
            self.runtime_states[instance.key] = instance
            return
        raise AssertionError(f"Unexpected add: {instance}")

    async def commit(self):
        self.committed = True

    async def refresh(self, _instance):
        self.refreshed = True


@pytest.mark.asyncio
async def test_get_equity_curve_returns_recent_points_and_latest(monkeypatch: pytest.MonkeyPatch):
    points = [
        json.dumps({"ts": "2026-03-24T00:00:00+00:00", "equity": 1000000}),
        json.dumps({"ts": "2026-03-24T00:01:00+00:00", "equity": 1010000}),
        json.dumps({"ts": "2026-03-24T00:02:00+00:00", "equity": 1020000}),
    ]
    fake_redis = _FakeRedis(
        items=points,
        latest=json.dumps({"ts": "2026-03-24T00:02:00+00:00", "equity": 1020000}).encode(),
    )
    monkeypatch.setattr(portfolio_module, "_get_redis", lambda: fake_redis)

    response = await portfolio_module.get_equity_curve(limit=2)

    assert response["data"] == [
        {"ts": "2026-03-24T00:01:00+00:00", "equity": 1010000},
        {"ts": "2026-03-24T00:02:00+00:00", "equity": 1020000},
    ]
    assert response["latest"] == {"ts": "2026-03-24T00:02:00+00:00", "equity": 1020000}
    assert fake_redis.closed is True


@pytest.mark.asyncio
async def test_get_equity_curve_handles_empty_store(monkeypatch: pytest.MonkeyPatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(portfolio_module, "_get_redis", lambda: fake_redis)

    response = await portfolio_module.get_equity_curve(limit=10)

    assert response == {"data": [], "latest": None}


@pytest.mark.asyncio
async def test_get_equity_curve_filters_by_days(monkeypatch: pytest.MonkeyPatch):
    points = [
        json.dumps({"ts": "2026-03-10T00:00:00+00:00", "equity": 900000}),
        json.dumps({"ts": "2026-03-24T00:00:00+00:00", "equity": 1000000}),
        json.dumps({"ts": "2026-03-25T00:00:00+00:00", "equity": 1010000}),
    ]
    fake_redis = _FakeRedis(
        items=points,
        latest=json.dumps({"ts": "2026-03-25T00:00:00+00:00", "equity": 1010000}).encode(),
    )

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 3, 25, 12, 0, tzinfo=tz or timezone.utc)

    monkeypatch.setattr(portfolio_module, "_get_redis", lambda: fake_redis)
    monkeypatch.setattr(portfolio_module, "datetime", _FrozenDateTime)

    response = await portfolio_module.get_equity_curve(limit=10, days=7)

    assert response["data"] == [
        {"ts": "2026-03-24T00:00:00+00:00", "equity": 1000000},
        {"ts": "2026-03-25T00:00:00+00:00", "equity": 1010000},
    ]
    assert response["latest"] == {"ts": "2026-03-25T00:00:00+00:00", "equity": 1010000}


@pytest.mark.asyncio
async def test_set_position_auto_trade_promotes_external_position(monkeypatch: pytest.MonkeyPatch):
    coin = Coin(
        id=42,
        market="KRW-DOGE",
        base_currency="DOGE",
        quote_currency="KRW",
        is_active=True,
        market_warning=None,
    )
    position = Position(
        id=7,
        coin_id=42,
        qty=35.71428571,
        avg_entry_price=140.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        source="external",
    )
    db = _FakeDB(coin=coin, position=position)

    monkeypatch.setattr(
        portfolio_module,
        "get_settings",
        lambda: SimpleNamespace(
            risk_default_stop_loss_pct=0.03,
            risk_default_take_profit_pct=0.06,
        ),
    )
    monkeypatch.setattr(portfolio_module, "record_audit_event", lambda **_kwargs: _noop())

    response = await portfolio_module.set_position_auto_trade(
        "KRW-DOGE",
        portfolio_module.PositionAutoTradeRequest(enabled=True),
        db,
    )

    runtime_state = await db.get(RuntimeState, portfolio_module._position_management_key(coin.id))

    assert response["market"] == "KRW-DOGE"
    assert response["source"] == "strategy"
    assert response["auto_trade_managed"] is True
    assert response["stop_loss"] == pytest.approx(135.8)
    assert response["take_profit"] == pytest.approx(148.4)
    assert position.source == "strategy"
    assert db.committed is True
    assert db.refreshed is True
    assert runtime_state is not None
    assert runtime_state.value == "strategy"


@pytest.mark.asyncio
async def test_get_positions_includes_latest_signal_and_sell_wait_reason(monkeypatch: pytest.MonkeyPatch):
    coin = Coin(
        id=42,
        market="KRW-DOGE",
        base_currency="DOGE",
        quote_currency="KRW",
        is_active=True,
        market_warning=None,
    )
    position = Position(
        id=7,
        coin_id=42,
        qty=35.71428571,
        avg_entry_price=140.0,
        unrealized_pnl=178.57,
        realized_pnl=0.0,
        source="strategy",
        stop_loss=135.8,
        take_profit=148.4,
    )

    class _PositionsDB:
        async def execute(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            if entity is Position:
                return _FakeRowsResult([(position, coin.market, coin.id)])
            if entity is portfolio_module.Signal:
                return _FakeRowsResult(
                    [
                        portfolio_module.Signal(
                            id=99,
                            strategy_id="hybrid_v1",
                            coin_id=coin.id,
                            timeframe="1m",
                            ts=datetime(2026, 3, 25, 10, 0, tzinfo=timezone.utc),
                            ta_score=0.45,
                            sentiment_score=0.20,
                            final_score=0.51,
                            confidence=0.76,
                            side="hold",
                            status="executed",
                            rejection_reason="held_position_hold",
                        )
                    ]
                )
            raise AssertionError(f"Unexpected entity: {entity}")

    monkeypatch.setattr(portfolio_module, "_get_hold_stale_minutes", lambda: _awaitable(180))

    response = await portfolio_module.get_positions(db=_PositionsDB())

    assert len(response) == 1
    assert response[0]["market"] == "KRW-DOGE"
    assert response[0]["auto_trade_managed"] is True
    assert response[0]["current_price"] == pytest.approx(145.0)
    assert response[0]["distance_to_stop_loss_pct"] == pytest.approx((145.0 - 135.8) / 145.0 * 100, abs=1e-4)
    assert response[0]["distance_to_take_profit_pct"] == pytest.approx((148.4 - 145.0) / 145.0 * 100, abs=1e-4)
    assert response[0]["latest_signal"]["side"] == "hold"
    assert response[0]["latest_signal"]["display_reason"] == "보유 포지션 유지 조건이라 관망 중입니다."
    assert response[0]["latest_sell_signal"] is None
    assert response[0]["sell_wait_reason_code"] == "hold_signal"
    assert "hold" in response[0]["sell_wait_reason"]
    assert response[0]["hold_stale_threshold_minutes"] == 180


@pytest.mark.asyncio
async def test_get_positions_includes_hold_stale_warning(monkeypatch: pytest.MonkeyPatch):
    coin = Coin(
        id=77,
        market="KRW-ADA",
        base_currency="ADA",
        quote_currency="KRW",
        is_active=True,
        market_warning=None,
    )
    position = Position(
        id=12,
        coin_id=77,
        qty=10.0,
        avg_entry_price=1000.0,
        unrealized_pnl=100.0,
        realized_pnl=0.0,
        source="strategy",
        stop_loss=970.0,
        take_profit=1060.0,
    )

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 3, 25, 12, 0, tzinfo=tz or timezone.utc)

    hold_signals = [
        portfolio_module.Signal(
            id=201,
            strategy_id="hybrid_v1",
            coin_id=coin.id,
            timeframe="1m",
            ts=datetime(2026, 3, 25, 11, 59, tzinfo=timezone.utc),
            ta_score=0.11,
            sentiment_score=0.20,
            final_score=0.18,
            confidence=0.71,
            side="hold",
            status="executed",
            rejection_reason="held_position_hold",
        ),
        portfolio_module.Signal(
            id=202,
            strategy_id="hybrid_v1",
            coin_id=coin.id,
            timeframe="1m",
            ts=datetime(2026, 3, 25, 8, 0, tzinfo=timezone.utc),
            ta_score=0.08,
            sentiment_score=0.18,
            final_score=0.15,
            confidence=0.69,
            side="hold",
            status="executed",
            rejection_reason="held_position_hold",
        ),
        portfolio_module.Signal(
            id=203,
            strategy_id="hybrid_v1",
            coin_id=coin.id,
            timeframe="1m",
            ts=datetime(2026, 3, 25, 7, 59, tzinfo=timezone.utc),
            ta_score=0.22,
            sentiment_score=0.30,
            final_score=0.28,
            confidence=0.80,
            side="buy",
            status="executed",
            rejection_reason=None,
        ),
    ]

    class _PositionsDB:
        async def execute(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            if entity is Position:
                return _FakeRowsResult([(position, coin.market, coin.id)])
            if entity is portfolio_module.Signal:
                return _FakeRowsResult(hold_signals)
            raise AssertionError(f"Unexpected entity: {entity}")

    monkeypatch.setattr(portfolio_module, "datetime", _FrozenDateTime)
    monkeypatch.setattr(portfolio_module, "_get_hold_stale_minutes", lambda: _awaitable(180))

    response = await portfolio_module.get_positions(db=_PositionsDB())

    assert response[0]["consecutive_hold_count"] == 2
    assert response[0]["hold_stale"] is True
    assert response[0]["hold_duration_minutes"] == pytest.approx(240.0)
    assert "연속 hold" in response[0]["hold_warning"]
    assert response[0]["hold_stale_threshold_minutes"] == 180


@pytest.mark.asyncio
async def test_get_positions_prefers_latest_sell_signal_reason_over_latest_general_signal(monkeypatch: pytest.MonkeyPatch):
    coin = Coin(
        id=99,
        market="KRW-SOL",
        base_currency="SOL",
        quote_currency="KRW",
        is_active=True,
        market_warning=None,
    )
    position = Position(
        id=10,
        coin_id=99,
        qty=0.1,
        avg_entry_price=100000.0,
        unrealized_pnl=500.0,
        realized_pnl=0.0,
        source="strategy",
        stop_loss=97000.0,
        take_profit=106000.0,
    )

    sell_signal = portfolio_module.Signal(
        id=101,
        strategy_id="hybrid_v1",
        coin_id=coin.id,
        timeframe="1m",
        ts=datetime(2026, 3, 25, 9, 0, tzinfo=timezone.utc),
        ta_score=0.33,
        sentiment_score=0.12,
        final_score=0.48,
        confidence=0.65,
        side="sell",
        status="rejected",
        rejection_reason="Max consecutive losses reached: 5",
    )
    newer_hold_signal = portfolio_module.Signal(
        id=102,
        strategy_id="hybrid_v1",
        coin_id=coin.id,
        timeframe="1m",
        ts=datetime(2026, 3, 25, 10, 0, tzinfo=timezone.utc),
        ta_score=0.29,
        sentiment_score=0.10,
        final_score=0.42,
        confidence=0.70,
        side="hold",
        status="new",
        rejection_reason=None,
    )

    class _PositionsDB:
        async def execute(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            if entity is Position:
                return _FakeRowsResult([(position, coin.market, coin.id)])
            if entity is portfolio_module.Signal:
                return _FakeRowsResult([newer_hold_signal, sell_signal])
            raise AssertionError(f"Unexpected entity: {entity}")

    monkeypatch.setattr(portfolio_module, "_get_hold_stale_minutes", lambda: _awaitable(180))

    response = await portfolio_module.get_positions(db=_PositionsDB())

    assert response[0]["latest_signal"]["side"] == "hold"
    assert response[0]["latest_sell_signal"]["side"] == "sell"
    assert response[0]["sell_wait_reason_code"] == "sell_signal_rejected"
    assert "Max consecutive losses reached" in response[0]["sell_wait_reason"]


def test_build_closed_trades_reconstructs_round_trip_from_fills():
    fills = [
        {
            "market": "KRW-BTC",
            "side": "bid",
            "price": 100.0,
            "volume": 1.0,
            "fee": 0.05,
            "filledAt": datetime(2026, 3, 25, 0, 0, tzinfo=timezone.utc),
            "signal": None,
            "strategyId": "hybrid_v1",
            "taScore": 0.4,
            "sentimentScore": 0.3,
            "finalScore": 0.36,
            "confidence": 0.9,
        },
        {
            "market": "KRW-BTC",
            "side": "ask",
            "price": 110.0,
            "volume": 1.0,
            "fee": 0.055,
            "filledAt": datetime(2026, 3, 25, 1, 0, tzinfo=timezone.utc),
            "signal": None,
            "orderReason": "SL triggered: 95 <= 97",
            "strategyId": None,
            "taScore": None,
            "sentimentScore": None,
            "finalScore": None,
            "confidence": None,
        },
    ]

    trades = portfolio_module._build_closed_trades(fills)

    assert len(trades) == 1
    assert trades[0]["market"] == "KRW-BTC"
    assert trades[0]["entryPrice"] == pytest.approx(100.0)
    assert trades[0]["exitPrice"] == pytest.approx(110.0)
    assert trades[0]["grossPnl"] == pytest.approx(10.0)
    assert trades[0]["netPnl"] == pytest.approx(9.895)
    assert trades[0]["exitReason"] == "stop_loss"
    assert trades[0]["strategyId"] == "hybrid_v1"


def test_build_closed_trades_splits_reentry_and_partial_exit_fifo():
    fills = [
        {
            "market": "KRW-BTC",
            "side": "bid",
            "price": 100.0,
            "volume": 1.0,
            "fee": 0.10,
            "filledAt": datetime(2026, 3, 25, 0, 0, tzinfo=timezone.utc),
            "signal": None,
            "strategyId": "entry_a",
            "taScore": 0.40,
            "sentimentScore": 0.10,
            "finalScore": 0.35,
            "confidence": 0.80,
        },
        {
            "market": "KRW-BTC",
            "side": "ask",
            "price": 110.0,
            "volume": 0.5,
            "fee": 0.05,
            "filledAt": datetime(2026, 3, 25, 0, 30, tzinfo=timezone.utc),
            "signal": None,
            "orderReason": "sell signal",
            "strategyId": None,
            "taScore": None,
            "sentimentScore": None,
            "finalScore": None,
            "confidence": None,
        },
        {
            "market": "KRW-BTC",
            "side": "bid",
            "price": 120.0,
            "volume": 1.0,
            "fee": 0.12,
            "filledAt": datetime(2026, 3, 25, 1, 0, tzinfo=timezone.utc),
            "signal": None,
            "strategyId": "entry_b",
            "taScore": 0.55,
            "sentimentScore": 0.20,
            "finalScore": 0.48,
            "confidence": 0.90,
        },
        {
            "market": "KRW-BTC",
            "side": "ask",
            "price": 130.0,
            "volume": 1.5,
            "fee": 0.15,
            "filledAt": datetime(2026, 3, 25, 2, 0, tzinfo=timezone.utc),
            "signal": None,
            "orderReason": "TP triggered: 130 >= 127",
            "strategyId": None,
            "taScore": None,
            "sentimentScore": None,
            "finalScore": None,
            "confidence": None,
        },
    ]

    trades = portfolio_module._build_closed_trades(fills)

    assert len(trades) == 3
    # exitTs desc order
    assert [trade["strategyId"] for trade in trades] == ["entry_a", "entry_b", "entry_a"]
    assert [trade["qty"] for trade in trades] == pytest.approx([0.5, 1.0, 0.5])
    assert trades[0]["entryPrice"] == pytest.approx(100.0)
    assert trades[0]["exitPrice"] == pytest.approx(130.0)
    assert trades[0]["exitReason"] == "take_profit"
    assert trades[1]["entryPrice"] == pytest.approx(120.0)
    assert trades[1]["exitPrice"] == pytest.approx(130.0)
    assert trades[1]["strategyId"] == "entry_b"
    assert trades[2]["entryPrice"] == pytest.approx(100.0)
    assert trades[2]["exitPrice"] == pytest.approx(110.0)
    assert trades[2]["exitReason"] == "protection"


def test_summarize_performance_computes_profit_factor_and_drawdown():
    trades = [
        {
            "market": "KRW-BTC",
            "exitReason": "sell_signal",
            "grossPnl": 12.0,
            "netPnl": 10.0,
            "finalScore": 0.82,
            "sentimentScore": 0.55,
            "exitTs": "2026-03-25T15:00:00+00:00",
        },
        {
            "market": "KRW-ETH",
            "exitReason": "protection",
            "grossPnl": -6.0,
            "netPnl": -8.0,
            "finalScore": 0.58,
            "sentimentScore": -0.10,
            "exitTs": "2026-03-25T01:00:00+00:00",
        },
        {
            "market": "KRW-XRP",
            "exitReason": "sell_signal",
            "grossPnl": 4.0,
            "netPnl": 2.0,
            "finalScore": 0.66,
            "sentimentScore": 0.18,
            "exitTs": "2026-03-25T07:00:00+00:00",
        },
    ]

    summary = portfolio_module._summarize_performance(trades)
    by_market = portfolio_module._group_performance(trades, "market")
    by_reason = portfolio_module._group_performance(trades, "exitReason")
    by_score_band = portfolio_module._group_score_band_performance(trades)
    by_sentiment_band = portfolio_module._group_sentiment_band_performance(trades)
    by_hour_block = portfolio_module._group_hour_block_performance(trades)

    assert summary["totalTrades"] == 3
    assert summary["winRate"] == pytest.approx(2 / 3)
    assert summary["netPnl"] == pytest.approx(4.0)
    assert summary["profitFactor"] == pytest.approx(12.0 / 8.0)
    assert summary["maxDrawdown"] == pytest.approx(8.0)
    assert by_market[0]["market"] == "KRW-BTC"
    assert by_reason[0]["exitReason"] == "sell_signal"
    assert [row["scoreBand"] for row in by_score_band] == ["0.50-0.59", "0.60-0.69", "0.80+"]
    assert by_score_band[0]["netPnl"] == pytest.approx(-8.0)
    assert [row["sentimentBand"] for row in by_sentiment_band] == ["-0.25~-0.01", "0.00-0.24", "0.50+"]
    assert by_sentiment_band[0]["netPnl"] == pytest.approx(-8.0)
    assert [row["hourBlock"] for row in by_hour_block] == ["00-04", "08-12", "16-20"]
    assert by_hour_block[2]["netPnl"] == pytest.approx(2.0)


def test_group_signal_transitions_aggregates_coin_sequences():
    rows = portfolio_module._group_signal_transitions(
        [
            portfolio_module.Signal(
                id=1,
                strategy_id="hybrid_v1",
                coin_id=1,
                timeframe="1m",
                ts=datetime(2026, 3, 25, 0, 0, tzinfo=timezone.utc),
                ta_score=0.3,
                sentiment_score=0.1,
                final_score=0.2,
                confidence=0.8,
                side="buy",
                status="executed",
            ),
            portfolio_module.Signal(
                id=2,
                strategy_id="hybrid_v1",
                coin_id=1,
                timeframe="1m",
                ts=datetime(2026, 3, 25, 0, 10, tzinfo=timezone.utc),
                ta_score=0.1,
                sentiment_score=0.0,
                final_score=0.1,
                confidence=0.8,
                side="hold",
                status="executed",
            ),
            portfolio_module.Signal(
                id=3,
                strategy_id="hybrid_v1",
                coin_id=1,
                timeframe="1m",
                ts=datetime(2026, 3, 25, 0, 25, tzinfo=timezone.utc),
                ta_score=-0.2,
                sentiment_score=0.0,
                final_score=-0.1,
                confidence=0.8,
                side="sell",
                status="new",
            ),
            portfolio_module.Signal(
                id=4,
                strategy_id="hybrid_v1",
                coin_id=2,
                timeframe="1m",
                ts=datetime(2026, 3, 25, 1, 0, tzinfo=timezone.utc),
                ta_score=0.3,
                sentiment_score=0.1,
                final_score=0.2,
                confidence=0.8,
                side="buy",
                status="executed",
            ),
            portfolio_module.Signal(
                id=5,
                strategy_id="hybrid_v1",
                coin_id=2,
                timeframe="1m",
                ts=datetime(2026, 3, 25, 1, 5, tzinfo=timezone.utc),
                ta_score=0.1,
                sentiment_score=0.0,
                final_score=0.1,
                confidence=0.8,
                side="hold",
                status="executed",
            ),
        ]
    )

    assert rows[0]["transition"] == "buy->hold"
    assert rows[0]["count"] == 2
    assert rows[0]["share"] == pytest.approx(2 / 3)
    assert rows[0]["avgGapMinutes"] == pytest.approx(7.5)
    assert rows[1]["transition"] == "hold->sell"
    assert rows[1]["count"] == 1


def test_group_market_transition_quality_flags_hold_heavy_markets():
    rows = portfolio_module._group_market_transition_quality(
        [
            {"market": "KRW-BTC", "side": "buy", "ts": datetime(2026, 3, 25, 0, 0, tzinfo=timezone.utc)},
            {"market": "KRW-BTC", "side": "hold", "ts": datetime(2026, 3, 25, 0, 10, tzinfo=timezone.utc)},
            {"market": "KRW-BTC", "side": "hold", "ts": datetime(2026, 3, 25, 0, 20, tzinfo=timezone.utc)},
            {"market": "KRW-BTC", "side": "sell", "ts": datetime(2026, 3, 25, 0, 35, tzinfo=timezone.utc)},
            {"market": "KRW-ETH", "side": "buy", "ts": datetime(2026, 3, 25, 1, 0, tzinfo=timezone.utc)},
            {"market": "KRW-ETH", "side": "hold", "ts": datetime(2026, 3, 25, 1, 10, tzinfo=timezone.utc)},
            {"market": "KRW-ETH", "side": "hold", "ts": datetime(2026, 3, 25, 1, 20, tzinfo=timezone.utc)},
        ]
    )

    assert rows[0]["market"] == "KRW-ETH"
    assert rows[0]["holdToSellRate"] == pytest.approx(0.0)
    assert rows[0]["holdToHoldRate"] == pytest.approx(1.0)
    assert rows[1]["market"] == "KRW-BTC"
    assert rows[1]["holdToSellRate"] == pytest.approx(0.5)


def test_get_market_transition_quality_returns_default_for_unknown_market():
    row = portfolio_module._get_market_transition_quality(
        [
            {"market": "KRW-BTC", "side": "buy", "ts": datetime(2026, 3, 25, 0, 0, tzinfo=timezone.utc)},
            {"market": "KRW-BTC", "side": "hold", "ts": datetime(2026, 3, 25, 0, 10, tzinfo=timezone.utc)},
        ],
        "KRW-ETH",
    )

    assert row == {
        "market": "KRW-ETH",
        "totalTransitions": 0,
        "holdOriginCount": 0,
        "holdToSellCount": 0,
        "holdToHoldCount": 0,
        "holdToBuyCount": 0,
        "holdToSellRate": 0.0,
        "holdToHoldRate": 0.0,
    }


def test_parse_excluded_market_state_supports_metadata_payload():
    state = portfolio_module._parse_excluded_market_state(
        json.dumps(
            {
                "items": [
                    {
                        "market": "krw-btc",
                        "reason": "hold->sell 낮음",
                        "updated_at": "2026-03-26T01:00:00+09:00",
                    }
                ]
            }
        )
    )

    assert state["markets"] == ["KRW-BTC"]
    assert state["items"][0]["reason"] == "hold->sell 낮음"


@pytest.mark.asyncio
async def test_get_portfolio_performance_reads_from_cache(monkeypatch: pytest.MonkeyPatch):
    cached_payload = {
        "summary": {"totalTrades": 1, "winRate": 1.0},
        "byMarket": [{"market": "KRW-BTC", "trades": 1, "winRate": 1.0, "netPnl": 100.0}],
        "byExitReason": [{"exitReason": "take_profit", "trades": 1, "winRate": 1.0, "netPnl": 100.0}],
        "byFinalScoreBand": [{"scoreBand": "0.80+", "trades": 1, "winRate": 1.0, "netPnl": 100.0}],
        "bySentimentBand": [{"sentimentBand": "0.50+", "trades": 1, "winRate": 1.0, "netPnl": 100.0}],
        "byHourBlock": [{"hourBlock": "20-24", "trades": 1, "winRate": 1.0, "netPnl": 100.0}],
        "trades": [{"market": "KRW-BTC", "exitReason": "take_profit", "netPnl": 100.0}],
    }
    fake_redis = _FakeRedis()
    fake_redis.values[portfolio_module._performance_cache_key(25, None, None)] = json.dumps(cached_payload)
    monkeypatch.setattr(portfolio_module, "_get_redis", lambda: fake_redis)

    class _FailDB:
        async def execute(self, _statement):
            raise AssertionError("DB should not be called when cache is warm")

    response = await portfolio_module.get_portfolio_performance(limit=25, db=_FailDB())

    assert response == cached_payload


@pytest.mark.asyncio
async def test_get_portfolio_performance_caches_and_separates_tp_reason(monkeypatch: pytest.MonkeyPatch):
    buy_fill = SimpleNamespace(
        price=100.0,
        volume=1.0,
        fee=0.05,
        filled_at=datetime(2026, 3, 25, 0, 0, tzinfo=timezone.utc),
    )
    sell_fill = SimpleNamespace(
        price=110.0,
        volume=1.0,
        fee=0.055,
        filled_at=datetime(2026, 3, 25, 1, 0, tzinfo=timezone.utc),
    )
    buy_order = SimpleNamespace(side="bid", rejected_reason=None, signal_id=1, coin_id=1)
    sell_order = SimpleNamespace(side="ask", rejected_reason="TP triggered: 110 >= 106", signal_id=None, coin_id=1)
    coin_market = "KRW-BTC"
    buy_signal = SimpleNamespace(
        id=1,
        coin_id=1,
        strategy_id="hybrid_v1",
        ts=datetime(2026, 3, 25, 0, 0, tzinfo=timezone.utc),
        ta_score=0.4,
        sentiment_score=0.3,
        final_score=0.36,
        confidence=0.9,
        side="buy",
    )

    class _PerfDB:
        def __init__(self):
            self.calls = 0

        async def execute(self, statement):
            self.calls += 1
            entity = statement.column_descriptions[0]["entity"]
            if entity is portfolio_module.Fill:
                return _FakeRowsResult(
                    [
                        (buy_fill, buy_order, coin_market, buy_signal),
                        (sell_fill, sell_order, coin_market, None),
                    ]
                )
            if entity is portfolio_module.Signal:
                return _FakeRowsResult([(buy_signal, coin_market)])
            raise AssertionError(f"Unexpected entity: {entity}")

    fake_db = _PerfDB()
    fake_redis = _FakeRedis()
    monkeypatch.setattr(portfolio_module, "_get_redis", lambda: fake_redis)

    response = await portfolio_module.get_portfolio_performance(limit=50, db=fake_db)

    assert fake_db.calls == 2
    assert response["summary"]["totalTrades"] == 1
    assert response["byExitReason"][0]["exitReason"] == "take_profit"
    assert response["byFinalScoreBand"][0]["scoreBand"] == "<0.50"
    assert response["bySentimentBand"][0]["sentimentBand"] == "0.25-0.49"
    assert response["byHourBlock"][0]["hourBlock"] == "08-12"
    assert response["byTransition"] == []
    assert response["trades"][0]["exitReason"] == "take_profit"
    cache_key = portfolio_module._performance_cache_key(50, None, None)
    assert cache_key in fake_redis.values
    assert fake_redis.expirations[cache_key] == portfolio_module.PORTFOLIO_PERFORMANCE_CACHE_TTL_SECONDS


@pytest.mark.asyncio
async def test_get_portfolio_performance_filters_by_days(monkeypatch: pytest.MonkeyPatch):
    recent_buy_fill = SimpleNamespace(
        price=100.0,
        volume=1.0,
        fee=0.05,
        filled_at=datetime(2026, 3, 24, 0, 0, tzinfo=timezone.utc),
    )
    recent_sell_fill = SimpleNamespace(
        price=105.0,
        volume=1.0,
        fee=0.05,
        filled_at=datetime(2026, 3, 24, 1, 0, tzinfo=timezone.utc),
    )
    old_buy_fill = SimpleNamespace(
        price=200.0,
        volume=1.0,
        fee=0.1,
        filled_at=datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc),
    )
    old_sell_fill = SimpleNamespace(
        price=210.0,
        volume=1.0,
        fee=0.1,
        filled_at=datetime(2026, 3, 10, 1, 0, tzinfo=timezone.utc),
    )
    buy_order = SimpleNamespace(side="bid", rejected_reason=None, signal_id=1, coin_id=1)
    sell_order = SimpleNamespace(side="ask", rejected_reason="TP triggered: 105 >= 103", signal_id=None, coin_id=1)
    buy_signal = SimpleNamespace(
        id=1,
        coin_id=1,
        strategy_id="hybrid_v1",
        ts=datetime(2026, 3, 24, 0, 0, tzinfo=timezone.utc),
        ta_score=0.4,
        sentiment_score=0.3,
        final_score=0.36,
        confidence=0.9,
        side="buy",
    )

    class _PerfDB:
        async def execute(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            if entity is portfolio_module.Fill:
                return _FakeRowsResult(
                    [
                        (old_buy_fill, buy_order, "KRW-ETH", buy_signal),
                        (old_sell_fill, sell_order, "KRW-ETH", None),
                        (recent_buy_fill, buy_order, "KRW-BTC", buy_signal),
                        (recent_sell_fill, sell_order, "KRW-BTC", None),
                    ]
                )
            if entity is portfolio_module.Signal:
                return _FakeRowsResult([(buy_signal, "KRW-BTC")])
            raise AssertionError(f"Unexpected entity: {entity}")

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 3, 25, 0, 0, tzinfo=tz or timezone.utc)

    fake_redis = _FakeRedis()
    monkeypatch.setattr(portfolio_module, "_get_redis", lambda: fake_redis)
    monkeypatch.setattr(portfolio_module, "datetime", _FrozenDateTime)

    response = await portfolio_module.get_portfolio_performance(limit=50, days=7, db=_PerfDB())

    assert response["summary"]["totalTrades"] == 1
    assert response["trades"][0]["market"] == "KRW-BTC"
    assert portfolio_module._performance_cache_key(50, 7, None) in fake_redis.values


@pytest.mark.asyncio
async def test_get_portfolio_performance_filters_by_market(monkeypatch: pytest.MonkeyPatch):
    buy_fill = SimpleNamespace(
        price=100.0,
        volume=1.0,
        fee=0.05,
        filled_at=datetime(2026, 3, 24, 0, 0, tzinfo=timezone.utc),
    )
    sell_fill = SimpleNamespace(
        price=105.0,
        volume=1.0,
        fee=0.05,
        filled_at=datetime(2026, 3, 24, 1, 0, tzinfo=timezone.utc),
    )
    buy_order = SimpleNamespace(side="bid", rejected_reason=None, signal_id=1, coin_id=1)
    sell_order = SimpleNamespace(side="ask", rejected_reason="TP triggered: 105 >= 103", signal_id=None, coin_id=1)
    buy_signal = SimpleNamespace(
        id=1,
        coin_id=1,
        strategy_id="hybrid_v1",
        ts=datetime(2026, 3, 24, 0, 0, tzinfo=timezone.utc),
        ta_score=0.4,
        sentiment_score=0.3,
        final_score=0.36,
        confidence=0.9,
        side="buy",
    )

    class _PerfDB:
        async def execute(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            if entity is portfolio_module.Fill:
                return _FakeRowsResult(
                    [
                        (buy_fill, buy_order, "KRW-BTC", buy_signal),
                        (sell_fill, sell_order, "KRW-BTC", None),
                        (buy_fill, buy_order, "KRW-ETH", buy_signal),
                        (sell_fill, sell_order, "KRW-ETH", None),
                    ]
                )
            if entity is portfolio_module.Signal:
                return _FakeRowsResult([(buy_signal, "KRW-ETH")])
            raise AssertionError(f"Unexpected entity: {entity}")

    fake_redis = _FakeRedis()
    monkeypatch.setattr(portfolio_module, "_get_redis", lambda: fake_redis)

    response = await portfolio_module.get_portfolio_performance(limit=50, market="krw-eth", db=_PerfDB())

    assert response["summary"]["totalTrades"] == 1
    assert response["trades"][0]["market"] == "KRW-ETH"
    assert portfolio_module._performance_cache_key(50, None, "KRW-ETH") in fake_redis.values


@pytest.mark.asyncio
async def test_get_market_transition_quality_filters_single_market():
    eth_buy = SimpleNamespace(
        id=1,
        coin_id=1,
        strategy_id="hybrid_v1",
        timeframe="1m",
        ts=datetime(2026, 3, 25, 0, 0, tzinfo=timezone.utc),
        ta_score=0.4,
        sentiment_score=0.2,
        final_score=0.3,
        confidence=0.8,
        side="buy",
        status="executed",
    )
    eth_hold = SimpleNamespace(
        id=2,
        coin_id=1,
        strategy_id="hybrid_v1",
        timeframe="1m",
        ts=datetime(2026, 3, 25, 0, 10, tzinfo=timezone.utc),
        ta_score=0.2,
        sentiment_score=0.1,
        final_score=0.1,
        confidence=0.7,
        side="hold",
        status="executed",
    )
    eth_sell = SimpleNamespace(
        id=3,
        coin_id=1,
        strategy_id="hybrid_v1",
        timeframe="1m",
        ts=datetime(2026, 3, 25, 0, 20, tzinfo=timezone.utc),
        ta_score=-0.4,
        sentiment_score=-0.1,
        final_score=-0.3,
        confidence=0.9,
        side="sell",
        status="executed",
    )
    btc_buy = SimpleNamespace(
        id=4,
        coin_id=2,
        strategy_id="hybrid_v1",
        timeframe="1m",
        ts=datetime(2026, 3, 25, 1, 0, tzinfo=timezone.utc),
        ta_score=0.5,
        sentiment_score=0.2,
        final_score=0.4,
        confidence=0.9,
        side="buy",
        status="executed",
    )

    class _TransitionDB:
        async def execute(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            assert entity is portfolio_module.Signal
            return _FakeRowsResult(
                [
                    (eth_buy, "KRW-ETH"),
                    (eth_hold, "KRW-ETH"),
                    (eth_sell, "KRW-ETH"),
                    (btc_buy, "KRW-BTC"),
                ]
            )

    response = await portfolio_module.get_market_transition_quality("krw-eth", db=_TransitionDB())

    assert response["market"] == "KRW-ETH"
    assert response["totalTransitions"] == 2
    assert response["holdOriginCount"] == 1
    assert response["holdToSellCount"] == 1
    assert response["holdToHoldCount"] == 0
    assert response["holdToSellRate"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_get_daily_report_includes_risk_audit_positions_and_exclusions(monkeypatch: pytest.MonkeyPatch):
    buy_fill = SimpleNamespace(
        id=1,
        price=100.0,
        volume=1.0,
        fee=0.05,
        filled_at=datetime(2026, 3, 26, 0, 10, tzinfo=timezone.utc),
    )
    sell_fill = SimpleNamespace(
        id=2,
        price=110.0,
        volume=1.0,
        fee=0.055,
        filled_at=datetime(2026, 3, 26, 1, 10, tzinfo=timezone.utc),
    )
    buy_order = SimpleNamespace(side="bid", rejected_reason=None, signal_id=1, coin_id=1)
    sell_order = SimpleNamespace(side="ask", rejected_reason="TP triggered: 110 >= 106", signal_id=None, coin_id=1)
    buy_signal = SimpleNamespace(
        id=1,
        coin_id=1,
        strategy_id="hybrid_v1",
        ts=datetime(2026, 3, 26, 0, 0, tzinfo=timezone.utc),
        ta_score=0.4,
        sentiment_score=0.3,
        final_score=0.36,
        confidence=0.9,
        side="buy",
    )
    open_position = Position(
        id=3,
        coin_id=2,
        qty=2.5,
        avg_entry_price=150.0,
        unrealized_pnl=-12.0,
        realized_pnl=5.0,
        source="strategy",
    )
    risk_event = SimpleNamespace(
        event_type="risk_rejected",
        created_at=datetime(2026, 3, 26, 3, 0, tzinfo=timezone.utc),
        message="risk_rejected KRW-ETH: Max consecutive losses reached: 5",
        payload_json=json.dumps({"reason": "Max consecutive losses reached: 5"}),
    )
    fail_event = SimpleNamespace(
        event_type="order_failed",
        created_at=datetime(2026, 3, 26, 4, 0, tzinfo=timezone.utc),
        message="order_failed KRW-ETH: insufficient_funds_bid",
        payload_json=json.dumps({"reason": "insufficient_funds_bid"}),
    )
    exclude_event = SimpleNamespace(
        event_type="excluded_market_added",
        created_at=datetime(2026, 3, 26, 5, 0, tzinfo=timezone.utc),
        message="excluded_market_added KRW-ETH",
        payload_json=json.dumps({"market": "KRW-ETH"}),
    )

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 3, 26, 12, 0, tzinfo=tz or timezone.utc)

    class _DailyReportDB:
        def __init__(self):
            self.runtime_states: dict[str, RuntimeState] = {}

        async def execute(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            if entity is portfolio_module.Fill:
                return _FakeRowsResult(
                    [
                        (buy_fill, buy_order, "KRW-BTC", buy_signal),
                        (sell_fill, sell_order, "KRW-BTC", None),
                    ]
                )
            if entity is portfolio_module.AuditEvent:
                return _FakeRowsResult([risk_event, fail_event, exclude_event])
            if entity is portfolio_module.Position:
                return _FakeRowsResult([(open_position, "KRW-ETH")])
            raise AssertionError(f"Unexpected entity: {entity}")

        async def get(self, model, key):
            if model is RuntimeState:
                return self.runtime_states.get(key)
            raise AssertionError(f"Unexpected model: {model}")

        def add(self, instance):
            if isinstance(instance, RuntimeState):
                self.runtime_states[instance.key] = instance
                return
            raise AssertionError(f"Unexpected add: {instance}")

        async def commit(self):
            return None

    db = _DailyReportDB()

    fake_redis = _FakeRedis()
    fake_redis.values["risk:daily_pnl:20260326"] = "1234.5"
    fake_redis.values[portfolio_module.RISK_LOSS_STREAK_REDIS_KEY] = "2"
    fake_redis.values[portfolio_module.EXCLUDED_MARKETS_REDIS_KEY] = json.dumps(
        {
            "items": [
                {
                    "market": "KRW-ETH",
                    "reason": "장기 hold 과다",
                    "updated_at": "2026-03-26T09:00:00+09:00",
                }
            ]
        }
    )
    monkeypatch.setattr(portfolio_module, "_get_redis", lambda: fake_redis)
    monkeypatch.setattr(portfolio_module, "datetime", _FrozenDateTime)

    response = await portfolio_module.get_daily_report(db=db)

    assert response["date"] == "20260326"
    assert response["summary"]["dailyPnl"] == pytest.approx(response["summary"]["netPnl"])
    assert response["summary"]["runtimeRiskDailyPnl"] == pytest.approx(1234.5)
    assert response["summary"]["lossStreak"] == 2
    assert response["summary"]["closedTrades"] == 1
    assert response["summary"]["openPositions"] == 1
    assert response["summary"]["excludedMarkets"] == 1
    assert response["summary"]["riskRejectedCount"] == 1
    assert response["summary"]["orderFailedCount"] == 1
    assert response["summary"]["excludedOpsCount"] == 1
    assert response["byExitReason"][0]["exitReason"] == "take_profit"
    assert response["analysis"]["byFinalScoreBand"][0]["scoreBand"] == "<0.50"
    assert response["analysis"]["weakMarkets"][0]["market"] == "KRW-BTC"
    assert response["analysis"]["riskRejectedReasons"][0]["reason"] == "Max consecutive losses reached: 5"
    assert response["analysis"]["riskRejectedReasons"][0]["count"] == 1
    assert response["positions"][0]["market"] == "KRW-ETH"
    assert response["positions"][0]["excluded"] is True
    assert response["positions"][0]["excludedReason"] == "장기 hold 과다"
    assert portfolio_module._daily_report_runtime_state_key("20260326") in db.runtime_states


@pytest.mark.asyncio
async def test_get_daily_report_history_returns_latest_snapshots_first():
    state_new = RuntimeState(
        key=portfolio_module._daily_report_runtime_state_key("20260326"),
        value=json.dumps({"date": "20260326", "summary": {"dailyPnl": 10}}),
    )
    state_old = RuntimeState(
        key=portfolio_module._daily_report_runtime_state_key("20260325"),
        value=json.dumps({"date": "20260325", "summary": {"dailyPnl": -5}}),
    )

    class _HistoryDB:
        def __init__(self):
            self.runtime_states = {
                state_new.key: state_new,
                state_old.key: state_old,
            }
            self.commits = 0

        async def execute(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            if entity is RuntimeState:
                return _FakeRowsResult([state_new, state_old])
            raise AssertionError(f"Unexpected entity: {entity}")

        async def get(self, model, key):
            if model is RuntimeState:
                return self.runtime_states.get(key)
            raise AssertionError(f"Unexpected model: {model}")

        def add(self, instance):
            if isinstance(instance, RuntimeState):
                self.runtime_states[instance.key] = instance
                return
            raise AssertionError(f"Unexpected add: {instance}")

        async def commit(self):
            self.commits += 1
    db = _HistoryDB()
    response = await portfolio_module.get_daily_report_history(limit=7, db=db)

    assert [row["date"] for row in response] == ["20260326", "20260325"]
    assert db.commits == 0


@pytest.mark.asyncio
async def test_backfill_daily_report_history_updates_snapshots_and_runtime_daily_pnl(monkeypatch: pytest.MonkeyPatch):
    buy_fill = SimpleNamespace(
        id=1,
        price=100.0,
        volume=1.0,
        fee=0.05,
        filled_at=datetime(2026, 3, 26, 0, 10, tzinfo=timezone.utc),
    )
    sell_fill = SimpleNamespace(
        id=2,
        price=110.0,
        volume=1.0,
        fee=0.055,
        filled_at=datetime(2026, 3, 26, 1, 10, tzinfo=timezone.utc),
    )
    buy_order = SimpleNamespace(side="bid", rejected_reason=None)
    sell_order = SimpleNamespace(side="ask", rejected_reason="TP triggered: 110 >= 106")
    buy_signal = SimpleNamespace(
        id=1,
        coin_id=1,
        strategy_id="hybrid_v1",
        ts=datetime(2026, 3, 26, 0, 0, tzinfo=timezone.utc),
        ta_score=0.4,
        sentiment_score=0.3,
        final_score=0.36,
        confidence=0.9,
        side="buy",
    )
    risk_event = SimpleNamespace(
        event_type="risk_rejected",
        created_at=datetime(2026, 3, 26, 3, 0, tzinfo=timezone.utc),
        message="risk_rejected KRW-BTC: Max consecutive losses reached: 5",
        payload_json=json.dumps({"reason": "Max consecutive losses reached: 5"}),
    )
    snapshot_state = RuntimeState(
        key=portfolio_module._daily_report_runtime_state_key("20260326"),
        value=json.dumps(
            {
                "date": "20260326",
                "summary": {"dailyPnl": 9999.0, "openPositions": 2},
                "positions": [{"market": "KRW-ETH"}],
            }
        ),
    )
    risk_daily_state = RuntimeState(key="risk.daily_pnl.20260326", value="1234.5")

    class _HistoryBackfillDB:
        def __init__(self):
            self.runtime_states = {
                snapshot_state.key: snapshot_state,
                risk_daily_state.key: risk_daily_state,
            }

        async def execute(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            if entity is RuntimeState:
                return _FakeRowsResult([snapshot_state])
            if entity is portfolio_module.Fill:
                return _FakeRowsResult(
                    [
                        (buy_fill, buy_order, "KRW-BTC", buy_signal),
                        (sell_fill, sell_order, "KRW-BTC", None),
                    ]
                )
            if entity is portfolio_module.AuditEvent:
                return _FakeRowsResult([risk_event])
            raise AssertionError(f"Unexpected entity: {entity}")

        async def get(self, model, key):
            if model is RuntimeState:
                return self.runtime_states.get(key)
            raise AssertionError(f"Unexpected model: {model}")

        def add(self, instance):
            if isinstance(instance, RuntimeState):
                self.runtime_states[instance.key] = instance
                return
            raise AssertionError(f"Unexpected add: {instance}")

        async def commit(self):
            return None

    audit_calls = []

    async def _fake_record_audit_event(**kwargs):
        audit_calls.append(kwargs)

    monkeypatch.setattr(portfolio_module, "record_audit_event", _fake_record_audit_event)

    db = _HistoryBackfillDB()
    response = await portfolio_module.backfill_daily_report_history(limit=7, db=db)

    updated_snapshot = json.loads(db.runtime_states[snapshot_state.key].value)

    assert response == {"processed": 1, "updated": 1, "failed": []}
    assert updated_snapshot["summary"]["dailyPnl"] == pytest.approx(updated_snapshot["summary"]["netPnl"])
    assert updated_snapshot["summary"]["runtimeRiskDailyPnl"] == pytest.approx(updated_snapshot["summary"]["dailyPnl"])
    assert updated_snapshot["summary"]["openPositions"] == 2
    assert updated_snapshot["positions"][0]["market"] == "KRW-ETH"
    assert updated_snapshot["byExitReason"][0]["exitReason"] == "take_profit"
    assert json.loads(db.runtime_states[snapshot_state.key].value)["summary"]["dailyPnl"] != 9999.0
    assert float(db.runtime_states[risk_daily_state.key].value) == pytest.approx(updated_snapshot["summary"]["dailyPnl"])
    assert audit_calls[0]["event_type"] == "daily_report_backfilled"


async def _noop():
    return None


async def _awaitable(value):
    return value

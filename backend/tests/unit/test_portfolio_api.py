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


class _FakeDB:
    def __init__(self, coin: Coin, position: Position):
        self.coin = coin
        self.position = position
        self.runtime_states: dict[str, RuntimeState] = {}
        self.committed = False
        self.refreshed = False

    async def execute(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity is Coin:
            return _FakeScalarResult(self.coin)
        if entity is Position:
            return _FakeScalarResult(self.position)
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


def test_summarize_performance_computes_profit_factor_and_drawdown():
    trades = [
        {"market": "KRW-BTC", "exitReason": "sell_signal", "grossPnl": 12.0, "netPnl": 10.0},
        {"market": "KRW-ETH", "exitReason": "protection", "grossPnl": -6.0, "netPnl": -8.0},
        {"market": "KRW-XRP", "exitReason": "sell_signal", "grossPnl": 4.0, "netPnl": 2.0},
    ]

    summary = portfolio_module._summarize_performance(trades)
    by_market = portfolio_module._group_performance(trades, "market")
    by_reason = portfolio_module._group_performance(trades, "exitReason")

    assert summary["totalTrades"] == 3
    assert summary["winRate"] == pytest.approx(2 / 3)
    assert summary["netPnl"] == pytest.approx(4.0)
    assert summary["profitFactor"] == pytest.approx(12.0 / 8.0)
    assert summary["maxDrawdown"] == pytest.approx(8.0)
    assert by_market[0]["market"] == "KRW-BTC"
    assert by_reason[0]["exitReason"] == "sell_signal"


@pytest.mark.asyncio
async def test_get_portfolio_performance_reads_from_cache(monkeypatch: pytest.MonkeyPatch):
    cached_payload = {
        "summary": {"totalTrades": 1, "winRate": 1.0},
        "byMarket": [{"market": "KRW-BTC", "trades": 1, "winRate": 1.0, "netPnl": 100.0}],
        "byExitReason": [{"exitReason": "take_profit", "trades": 1, "winRate": 1.0, "netPnl": 100.0}],
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
        strategy_id="hybrid_v1",
        ta_score=0.4,
        sentiment_score=0.3,
        final_score=0.36,
        confidence=0.9,
        side="buy",
    )

    class _PerfDB:
        def __init__(self):
            self.calls = 0

        async def execute(self, _statement):
            self.calls += 1
            return _FakeRowsResult(
                [
                    (buy_fill, buy_order, coin_market, buy_signal),
                    (sell_fill, sell_order, coin_market, None),
                ]
            )

    fake_db = _PerfDB()
    fake_redis = _FakeRedis()
    monkeypatch.setattr(portfolio_module, "_get_redis", lambda: fake_redis)

    response = await portfolio_module.get_portfolio_performance(limit=50, db=fake_db)

    assert fake_db.calls == 1
    assert response["summary"]["totalTrades"] == 1
    assert response["byExitReason"][0]["exitReason"] == "take_profit"
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
        strategy_id="hybrid_v1",
        ta_score=0.4,
        sentiment_score=0.3,
        final_score=0.36,
        confidence=0.9,
        side="buy",
    )

    class _PerfDB:
        async def execute(self, _statement):
            return _FakeRowsResult(
                [
                    (old_buy_fill, buy_order, "KRW-ETH", buy_signal),
                    (old_sell_fill, sell_order, "KRW-ETH", None),
                    (recent_buy_fill, buy_order, "KRW-BTC", buy_signal),
                    (recent_sell_fill, sell_order, "KRW-BTC", None),
                ]
            )

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
        strategy_id="hybrid_v1",
        ta_score=0.4,
        sentiment_score=0.3,
        final_score=0.36,
        confidence=0.9,
        side="buy",
    )

    class _PerfDB:
        async def execute(self, _statement):
            return _FakeRowsResult(
                [
                    (buy_fill, buy_order, "KRW-BTC", buy_signal),
                    (sell_fill, sell_order, "KRW-BTC", None),
                    (buy_fill, buy_order, "KRW-ETH", buy_signal),
                    (sell_fill, sell_order, "KRW-ETH", None),
                ]
            )

    fake_redis = _FakeRedis()
    monkeypatch.setattr(portfolio_module, "_get_redis", lambda: fake_redis)

    response = await portfolio_module.get_portfolio_performance(limit=50, market="krw-eth", db=_PerfDB())

    assert response["summary"]["totalTrades"] == 1
    assert response["trades"][0]["market"] == "KRW-ETH"
    assert portfolio_module._performance_cache_key(50, None, "KRW-ETH") in fake_redis.values


async def _noop():
    return None

import json
from types import SimpleNamespace

import pytest

from apps.gateway.api.v1 import portfolio as portfolio_module
from libs.db.models import Coin, Position, RuntimeState


class _FakeRedis:
    def __init__(self, items=None, latest=None):
        self.items = items or []
        self.latest = latest
        self.closed = False

    async def lrange(self, _key, start, end):
        if not self.items:
            return []
        resolved_end = None if end == -1 else end + 1
        return self.items[start:resolved_end]

    async def get(self, _key):
        return self.latest

    async def aclose(self):
        self.closed = True


class _FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


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


async def _noop():
    return None

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.gateway.api.v1 import manual_orders as manual_orders_module


class _FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeSession:
    def __init__(self, coin):
        self.coin = coin
        self.added = []

    async def execute(self, _stmt):
        return _FakeResult(self.coin)

    def add(self, obj):
        obj.id = 99
        self.added.append(obj)

    async def flush(self):
        return None


class _FakeUpbitClient:
    async def get_ticker(self, _market: str) -> float:
        return 100.0


@pytest.mark.asyncio
async def test_create_manual_buy_order_enqueues_manual_test_signal(monkeypatch: pytest.MonkeyPatch):
    fake_coin = SimpleNamespace(id=7, market="KRW-XRP")
    fake_db = _FakeSession(fake_coin)

    events = []

    async def _fake_record_audit_event(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr(manual_orders_module, "_is_manual_test_mode_enabled", lambda: _true())
    monkeypatch.setattr(manual_orders_module, "UpbitRestClient", lambda: _FakeUpbitClient())
    monkeypatch.setattr(manual_orders_module, "record_audit_event", _fake_record_audit_event)

    response = await manual_orders_module.create_manual_order(
        manual_orders_module.ManualOrderRequest(
            market="krw-xrp",
            side="buy",
            krw_amount=5000,
        ),
        db=fake_db,
    )

    assert response["signalId"] == 99
    assert response["strategyId"] == "manual-test"
    assert response["market"] == "KRW-XRP"
    assert response["side"] == "buy"
    assert response["suggestedQty"] == pytest.approx(50.0)
    assert fake_db.added[0].strategy_id == "manual-test"
    assert fake_db.added[0].suggested_qty == pytest.approx(50.0)
    assert events[0]["event_type"] == "manual_order_requested"


@pytest.mark.asyncio
async def test_create_manual_order_requires_test_mode(monkeypatch: pytest.MonkeyPatch):
    fake_coin = SimpleNamespace(id=7, market="KRW-XRP")
    fake_db = _FakeSession(fake_coin)

    monkeypatch.setattr(manual_orders_module, "_is_manual_test_mode_enabled", lambda: _false())

    with pytest.raises(HTTPException) as exc_info:
        await manual_orders_module.create_manual_order(
            manual_orders_module.ManualOrderRequest(
                market="KRW-XRP",
                side="buy",
                krw_amount=5000,
            ),
            db=fake_db,
        )

    assert exc_info.value.status_code == 409


async def _true():
    return True


async def _false():
    return False

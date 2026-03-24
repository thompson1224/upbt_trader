import json

import pytest

from apps.market_data_service import main as market_data_module


class _FakeRedis:
    def __init__(self):
        self.messages = []

    async def publish(self, channel, payload):
        self.messages.append((channel, json.loads(payload)))


@pytest.mark.asyncio
async def test_on_tick_buckets_ticks_by_market_and_minute(monkeypatch: pytest.MonkeyPatch):
    fake_redis = _FakeRedis()
    async def _fake_get_redis():
        return fake_redis

    monkeypatch.setattr(market_data_module, "_get_redis", _fake_get_redis)
    market_data_module._candle_buffer.clear()

    first_tick = {"ty": "ticker", "cd": "KRW-BTC", "tp": 100.0, "tv": 1.0, "tms": 1704067200000}
    second_tick = {"ty": "ticker", "cd": "KRW-BTC", "tp": 101.0, "tv": 2.0, "tms": 1704067260000}

    await market_data_module.on_tick(first_tick)
    await market_data_module.on_tick(second_tick)

    assert set(market_data_module._candle_buffer.keys()) == {
        ("KRW-BTC", "2024-01-01T00:00"),
        ("KRW-BTC", "2024-01-01T00:01"),
    }
    assert fake_redis.messages[0][0] == "upbit:ticker"
    assert fake_redis.messages[1][1]["tp"] == 101.0


@pytest.mark.asyncio
async def test_on_tick_ignores_non_ticker_messages(monkeypatch: pytest.MonkeyPatch):
    fake_redis = _FakeRedis()
    async def _fake_get_redis():
        return fake_redis

    monkeypatch.setattr(market_data_module, "_get_redis", _fake_get_redis)
    market_data_module._candle_buffer.clear()

    await market_data_module.on_tick({"ty": "trade", "cd": "KRW-BTC", "tms": 1704067200000})

    assert market_data_module._candle_buffer == {}
    assert fake_redis.messages == []

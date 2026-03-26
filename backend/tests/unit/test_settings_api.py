import pytest
from cryptography.fernet import Fernet

from apps.gateway.api.v1 import settings as settings_module


class _FakeRedis:
    def __init__(self):
        self.store = {}
        self.closed = False

    async def set(self, key, value):
        self.store[key] = value

    async def get(self, key):
        value = self.store.get(key)
        if value is None:
            return None
        if isinstance(value, bytes):
            return value
        return str(value).encode()

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_set_upbit_keys_stores_encrypted_values(monkeypatch: pytest.MonkeyPatch):
    encryption_key = Fernet.generate_key().decode()
    fake_redis = _FakeRedis()

    monkeypatch.setenv("ENCRYPTION_KEY", encryption_key)
    monkeypatch.setattr(settings_module, "_get_redis", lambda: fake_redis)
    monkeypatch.setattr(settings_module, "record_audit_event", lambda **_kwargs: _noop())

    request = settings_module.UpbitKeyRequest(
        access_key="plain-access",
        secret_key="plain-secret",
    )

    await settings_module.set_upbit_keys(request)

    cipher = Fernet(encryption_key.encode())
    encrypted_access = fake_redis.store[settings_module.UPBIT_ACCESS_KEY_REDIS_KEY]
    encrypted_secret = fake_redis.store[settings_module.UPBIT_SECRET_KEY_REDIS_KEY]

    assert encrypted_access != "plain-access"
    assert encrypted_secret != "plain-secret"
    assert cipher.decrypt(encrypted_access.encode()).decode() == "plain-access"
    assert cipher.decrypt(encrypted_secret.encode()).decode() == "plain-secret"
    assert fake_redis.closed is True


@pytest.mark.asyncio
async def test_auto_trade_flag_roundtrip(monkeypatch: pytest.MonkeyPatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(settings_module, "_get_redis", lambda: fake_redis)
    monkeypatch.setattr(settings_module, "record_audit_event", lambda **_kwargs: _noop())

    response = await settings_module.set_auto_trade(
        settings_module.AutoTradeRequest(enabled=False)
    )
    current = await settings_module.get_auto_trade()

    assert response == {"enabled": False}
    assert current == {"enabled": False}


@pytest.mark.asyncio
async def test_external_position_stop_loss_flag_roundtrip(monkeypatch: pytest.MonkeyPatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(settings_module, "_get_redis", lambda: fake_redis)
    monkeypatch.setattr(settings_module, "record_audit_event", lambda **_kwargs: _noop())

    response = await settings_module.set_external_position_stop_loss(
        settings_module.ExternalPositionProtectionRequest(enabled=True)
    )
    current = await settings_module.get_external_position_stop_loss()

    assert response == {"enabled": True}
    assert current == {"enabled": True}


@pytest.mark.asyncio
async def test_manual_test_mode_flag_roundtrip(monkeypatch: pytest.MonkeyPatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(settings_module, "_get_redis", lambda: fake_redis)
    monkeypatch.setattr(settings_module, "record_audit_event", lambda **_kwargs: _noop())

    response = await settings_module.set_manual_test_mode(
        settings_module.ManualTestModeRequest(enabled=True)
    )
    current = await settings_module.get_manual_test_mode()

    assert response == {"enabled": True}
    assert current == {"enabled": True}


@pytest.mark.asyncio
async def test_min_buy_final_score_roundtrip(monkeypatch: pytest.MonkeyPatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(settings_module, "_get_redis", lambda: fake_redis)
    monkeypatch.setattr(settings_module, "record_audit_event", lambda **_kwargs: _noop())

    response = await settings_module.set_min_buy_final_score(
        settings_module.MinBuyFinalScoreRequest(value=0.6)
    )
    current = await settings_module.get_min_buy_final_score()

    assert response == {"value": 0.6}
    assert current == {"value": 0.6}


@pytest.mark.asyncio
async def test_blocked_buy_hour_blocks_roundtrip(monkeypatch: pytest.MonkeyPatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(settings_module, "_get_redis", lambda: fake_redis)
    monkeypatch.setattr(settings_module, "record_audit_event", lambda **_kwargs: _noop())

    response = await settings_module.set_blocked_buy_hour_blocks(
        settings_module.BlockedBuyHourBlocksRequest(blocks=["08-12", "04-08", "08-12"])
    )
    current = await settings_module.get_blocked_buy_hour_blocks()

    assert response == {"blocks": ["04-08", "08-12"]}
    assert current == {"blocks": ["04-08", "08-12"]}


@pytest.mark.asyncio
async def test_hold_stale_minutes_roundtrip(monkeypatch: pytest.MonkeyPatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(settings_module, "_get_redis", lambda: fake_redis)
    monkeypatch.setattr(settings_module, "record_audit_event", lambda **_kwargs: _noop())

    response = await settings_module.set_hold_stale_minutes(
        settings_module.HoldStaleMinutesRequest(value=240)
    )
    current = await settings_module.get_hold_stale_minutes()

    assert response == {"value": 240}
    assert current == {"value": 240}


@pytest.mark.asyncio
async def test_transition_recommendation_settings_roundtrip(monkeypatch: pytest.MonkeyPatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(settings_module, "_get_redis", lambda: fake_redis)
    monkeypatch.setattr(settings_module, "record_audit_event", lambda **_kwargs: _noop())

    response = await settings_module.set_transition_recommendation_settings(
        settings_module.TransitionRecommendationSettingsRequest(
            min_hold_origin_count=4,
            exclude_max_hold_to_sell_rate=0.15,
            exclude_min_hold_to_hold_rate=0.7,
            restore_min_hold_to_sell_rate=0.45,
            restore_max_hold_to_hold_rate=0.25,
        )
    )
    current = await settings_module.get_transition_recommendation_settings()

    assert response == {
        "min_hold_origin_count": 4,
        "exclude_max_hold_to_sell_rate": 0.15,
        "exclude_min_hold_to_hold_rate": 0.7,
        "restore_min_hold_to_sell_rate": 0.45,
        "restore_max_hold_to_hold_rate": 0.25,
    }
    assert current == response


@pytest.mark.asyncio
async def test_excluded_markets_roundtrip(monkeypatch: pytest.MonkeyPatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(settings_module, "_get_redis", lambda: fake_redis)
    monkeypatch.setattr(settings_module, "record_audit_event", lambda **_kwargs: _noop())

    response = await settings_module.set_excluded_markets(
        settings_module.ExcludedMarketsRequest(markets=["krw-btc", " KRW-ETH ", ""])
    )
    current = await settings_module.get_excluded_markets()

    assert response["markets"] == ["KRW-BTC", "KRW-ETH"]
    assert [item["market"] for item in response["items"]] == ["KRW-BTC", "KRW-ETH"]
    assert [item["reason"] for item in response["items"]] == ["", ""]
    assert all(item["updated_at"] for item in response["items"])
    assert current == response


@pytest.mark.asyncio
async def test_excluded_markets_emits_diff_audit_events(monkeypatch: pytest.MonkeyPatch):
    fake_redis = _FakeRedis()
    fake_redis.store[settings_module.EXCLUDED_MARKETS_REDIS_KEY] = (
        '{"items": [{"market": "KRW-BTC", "reason": "old reason", "updated_at": "2026-03-26T00:00:00"}, '
        '{"market": "KRW-ETH", "reason": "", "updated_at": "2026-03-26T00:00:00"}]}'
    )
    events = []

    async def _capture_audit(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr(settings_module, "_get_redis", lambda: fake_redis)
    monkeypatch.setattr(settings_module, "record_audit_event", _capture_audit)

    response = await settings_module.set_excluded_markets(
        settings_module.ExcludedMarketsRequest(
            items=[
                settings_module.ExcludedMarketItem(market="KRW-BTC", reason="new reason"),
                settings_module.ExcludedMarketItem(market="KRW-XRP", reason="weak transitions"),
            ]
        )
    )

    assert response["markets"] == ["KRW-BTC", "KRW-XRP"]
    assert [event["event_type"] for event in events] == [
        "excluded_markets_updated",
        "excluded_market_added",
        "excluded_market_restored",
        "excluded_market_reason_updated",
    ]
    summary = events[0]
    assert summary["payload"]["added"] == ["KRW-XRP"]
    assert summary["payload"]["removed"] == ["KRW-ETH"]
    assert summary["payload"]["reasonChanged"] == ["KRW-BTC"]
    assert events[1]["market"] == "KRW-XRP"
    assert events[2]["market"] == "KRW-ETH"
    assert events[3]["market"] == "KRW-BTC"
    assert events[3]["payload"]["previous_reason"] == "old reason"
    assert events[3]["payload"]["reason"] == "new reason"


@pytest.mark.asyncio
async def test_reset_loss_streak_resets_redis_and_runtime_state(monkeypatch: pytest.MonkeyPatch):
    fake_redis = _FakeRedis()
    persisted = {}

    async def _persist(values):
        persisted.update(values)

    monkeypatch.setattr(settings_module, "_get_redis", lambda: fake_redis)
    monkeypatch.setattr(settings_module, "_persist_runtime_state_values", _persist)
    monkeypatch.setattr(settings_module, "record_audit_event", lambda **_kwargs: _noop())
    monkeypatch.setattr(settings_module, "_risk_metric_date", lambda now=None: "20260325")

    response = await settings_module.reset_loss_streak()

    assert response == {"lossStreak": 0, "streakDate": "20260325"}
    assert fake_redis.store[settings_module.RISK_LOSS_STREAK_REDIS_KEY] == "0"
    assert fake_redis.store[settings_module.RISK_LOSS_STREAK_DATE_REDIS_KEY] == "20260325"
    assert persisted == {
        settings_module.RUNTIME_STATE_LOSS_STREAK_KEY: "0",
        settings_module.RUNTIME_STATE_LOSS_STREAK_DATE_KEY: "20260325",
    }


async def _noop():
    return None

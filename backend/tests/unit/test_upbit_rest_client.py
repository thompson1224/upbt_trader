from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet

from libs.upbit import rest_client as rest_client_module


class _FakeRedis:
    def __init__(self, access_value=None, secret_value=None):
        self.access_value = access_value
        self.secret_value = secret_value
        self.closed = False

    async def mget(self, *_args):
        return self.access_value, self.secret_value

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_get_api_keys_prefers_encrypted_redis_keys(monkeypatch: pytest.MonkeyPatch):
    encryption_key = Fernet.generate_key().decode()
    cipher = Fernet(encryption_key.encode())
    redis_client = _FakeRedis(
        cipher.encrypt(b"redis-access"),
        cipher.encrypt(b"redis-secret"),
    )

    monkeypatch.setenv("ENCRYPTION_KEY", encryption_key)
    monkeypatch.setenv("UPBIT_ACCESS_KEY", "env-access")
    monkeypatch.setenv("UPBIT_SECRET_KEY", "env-secret")
    monkeypatch.setattr(
        rest_client_module,
        "get_settings",
        lambda: SimpleNamespace(
            upbit_access_key="settings-access",
            upbit_secret_key="settings-secret",
            encryption_key=encryption_key,
        ),
    )
    monkeypatch.setattr(rest_client_module.aioredis, "from_url", lambda _url: redis_client)

    client = rest_client_module.UpbitRestClient()
    access_key, secret_key = await client._get_api_keys()

    assert access_key == "redis-access"
    assert secret_key == "redis-secret"
    assert redis_client.closed is True


@pytest.mark.asyncio
async def test_get_api_keys_falls_back_to_env_when_redis_is_empty(monkeypatch: pytest.MonkeyPatch):
    encryption_key = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", encryption_key)
    monkeypatch.setenv("UPBIT_ACCESS_KEY", "env-access")
    monkeypatch.setenv("UPBIT_SECRET_KEY", "env-secret")
    monkeypatch.setattr(
        rest_client_module,
        "get_settings",
        lambda: SimpleNamespace(
            upbit_access_key="settings-access",
            upbit_secret_key="settings-secret",
            encryption_key=encryption_key,
        ),
    )
    monkeypatch.setattr(
        rest_client_module.aioredis,
        "from_url",
        lambda _url: _FakeRedis(None, None),
    )

    client = rest_client_module.UpbitRestClient()
    access_key, secret_key = await client._get_api_keys()

    assert access_key == "env-access"
    assert secret_key == "env-secret"


def test_compute_retry_delay_prefers_retry_after_header():
    delay = rest_client_module._compute_retry_delay({"Retry-After": "1.25"}, attempt=2)
    assert delay == pytest.approx(1.25)


def test_format_http_status_error_includes_json_payload():
    request = httpx.Request("POST", "https://api.upbit.com/v1/orders")
    response = httpx.Response(
        400,
        request=request,
        json={"error": {"name": "under_min_total_bid", "message": "최소 주문 금액 미만"}},
    )
    error = httpx.HTTPStatusError("bad request", request=request, response=response)

    message = rest_client_module._format_http_status_error(error)

    assert "payload=" in message
    assert "under_min_total_bid" in message


@pytest.mark.asyncio
async def test_get_tickers_returns_price_map(monkeypatch: pytest.MonkeyPatch):
    async def fake_request_json(_self, method, path, **kwargs):
        assert method == "GET"
        assert path == "/ticker"
        assert kwargs["params"]["markets"] == "KRW-BTC,KRW-ETH"
        return [
            {"market": "KRW-BTC", "trade_price": 100.0},
            {"market": "KRW-ETH", "trade_price": 200.0},
        ]

    monkeypatch.setattr(rest_client_module.UpbitRestClient, "_request_json", fake_request_json)

    client = rest_client_module.UpbitRestClient()
    result = await client.get_tickers(["KRW-BTC", "KRW-ETH", "KRW-BTC"])

    assert result == {"KRW-BTC": 100.0, "KRW-ETH": 200.0}

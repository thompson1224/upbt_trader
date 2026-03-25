from __future__ import annotations
"""pyupbit 래퍼 - REST API 클라이언트"""
import asyncio
import hashlib
import os
import jwt
import uuid
from typing import Any
from urllib.parse import urlencode

import httpx
import pyupbit
import redis.asyncio as aioredis
from cryptography.fernet import Fernet

from libs.config import get_settings

UPBIT_REST_BASE = "https://api.upbit.com/v1"
UPBIT_ACCESS_KEY_REDIS_KEY = "secret:upbit:access"
UPBIT_SECRET_KEY_REDIS_KEY = "secret:upbit:secret"
UPBIT_HTTP_TIMEOUT_SEC = 10.0
UPBIT_RETRY_BASE_DELAY_SEC = 0.5
UPBIT_MAX_RETRIES = 3


def _format_http_status_error(error: httpx.HTTPStatusError) -> str:
    response = error.response
    detail = ""
    try:
        payload = response.json()
        if payload:
            detail = f" payload={payload}"
    except ValueError:
        text = response.text.strip()
        if text:
            detail = f" body={text[:500]}"
    return f"{error}{detail}"


def _compute_retry_delay(headers: dict[str, str], attempt: int) -> float:
    retry_after = headers.get("Retry-After")
    if retry_after:
        try:
            return max(float(retry_after), 0.0)
        except ValueError:
            pass
    return UPBIT_RETRY_BASE_DELAY_SEC * (2 ** attempt)


class UpbitRestClient:
    """
    업비트 REST API 클라이언트.
    - pyupbit 활용 (공개 API)
    - 인증 API는 직접 JWT 발급
    """

    def __init__(self):
        self.settings = get_settings()
        self.redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        self.encryption_key = os.environ.get("ENCRYPTION_KEY", self.settings.encryption_key)

    def _generate_token(
        self,
        access_key: str,
        secret_key: str,
        query_params: dict | None = None,
    ) -> str:
        payload = {
            "access_key": access_key,
            "nonce": str(uuid.uuid4()),
        }
        if query_params:
            query_string = urlencode(query_params).encode()
            m = hashlib.sha512()
            m.update(query_string)
            payload["query_hash"] = m.hexdigest()
            payload["query_hash_alg"] = "SHA512"

        return jwt.encode(payload, secret_key, algorithm="HS256")

    async def _get_api_keys(self) -> tuple[str, str]:
        access_key = ""
        secret_key = ""

        if self.encryption_key:
            redis_client = aioredis.from_url(self.redis_url)
            try:
                encrypted_access, encrypted_secret = await redis_client.mget(
                    UPBIT_ACCESS_KEY_REDIS_KEY,
                    UPBIT_SECRET_KEY_REDIS_KEY,
                )
            except Exception:
                encrypted_access, encrypted_secret = None, None
            finally:
                await redis_client.aclose()

            if encrypted_access and encrypted_secret:
                fernet = Fernet(self.encryption_key.encode())
                access_key = fernet.decrypt(encrypted_access).decode()
                secret_key = fernet.decrypt(encrypted_secret).decode()

        access_key = access_key or os.environ.get("UPBIT_ACCESS_KEY", "") or self.settings.upbit_access_key
        secret_key = secret_key or os.environ.get("UPBIT_SECRET_KEY", "") or self.settings.upbit_secret_key

        if not access_key or not secret_key:
            raise RuntimeError("Upbit API keys are not configured")

        return access_key, secret_key

    async def _build_auth_headers(self, query_params: dict | None = None) -> dict[str, str]:
        access_key, secret_key = await self._get_api_keys()
        token = self._generate_token(access_key, secret_key, query_params)
        return {"Authorization": f"Bearer {token}"}

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retry_safe: bool = True,
    ) -> Any:
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=UPBIT_HTTP_TIMEOUT_SEC) as client:
            for attempt in range(UPBIT_MAX_RETRIES + 1):
                try:
                    resp = await client.request(
                        method,
                        f"{UPBIT_REST_BASE}/{path.lstrip('/')}",
                        params=params,
                        json=json_body,
                        headers=headers,
                    )
                    if resp.status_code == 429 and attempt < UPBIT_MAX_RETRIES:
                        await asyncio.sleep(_compute_retry_delay(resp.headers, attempt))
                        continue
                    if resp.status_code >= 500 and retry_safe and attempt < UPBIT_MAX_RETRIES:
                        await asyncio.sleep(_compute_retry_delay(resp.headers, attempt))
                        continue
                    resp.raise_for_status()
                    return resp.json()
                except httpx.RequestError as e:
                    last_error = e
                    if not retry_safe or attempt >= UPBIT_MAX_RETRIES:
                        raise
                    await asyncio.sleep(UPBIT_RETRY_BASE_DELAY_SEC * (2 ** attempt))
                except httpx.HTTPStatusError as e:
                    last_error = e
                    raise RuntimeError(_format_http_status_error(e)) from e

        if last_error:
            raise last_error
        raise RuntimeError(f"Upbit request failed: {method} {path}")

    async def get_krw_markets(self) -> list[dict]:
        """KRW 마켓 전체 목록 조회."""
        loop = asyncio.get_event_loop()
        tickers = await loop.run_in_executor(None, pyupbit.get_tickers, "KRW")
        markets = await loop.run_in_executor(
            None,
            lambda: pyupbit.get_tickers(fiat="KRW", verbose=True),
        )
        return markets or []

    async def get_ohlcv(
        self,
        market: str,
        interval: str = "minute1",
        count: int = 200,
    ) -> list[dict]:
        """캔들 데이터 조회."""
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(
            None,
            lambda: pyupbit.get_ohlcv(market, interval=interval, count=count),
        )
        if df is None:
            return []
        df = df.reset_index()
        df.columns = ["ts", "open", "high", "low", "close", "volume", "value"]
        return df.to_dict("records")

    async def get_ticker(self, market: str) -> float | None:
        """현재가 조회 (공개 API)."""
        data = await self._request_json(
            "GET",
            "/ticker",
            params={"markets": market},
            retry_safe=True,
        )
        if data:
            return float(data[0]["trade_price"])
        return None

    async def get_tickers(self, markets: list[str]) -> dict[str, float]:
        """여러 현재가를 한 번에 조회."""
        codes = [market for market in dict.fromkeys(markets) if market]
        if not codes:
            return {}
        data = await self._request_json(
            "GET",
            "/ticker",
            params={"markets": ",".join(codes)},
            retry_safe=True,
        )
        return {
            str(item["market"]): float(item["trade_price"])
            for item in data or []
        }

    async def get_balances(self) -> list[dict]:
        """계좌 잔고 조회."""
        headers = await self._build_auth_headers()
        return await self._request_json(
            "GET",
            "/accounts",
            headers=headers,
            retry_safe=True,
        )

    async def place_order(
        self,
        market: str,
        side: str,  # bid(매수) / ask(매도)
        volume: float | None,
        price: float | None,
        ord_type: str,  # limit / price / market
    ) -> dict:
        """주문 실행."""
        params: dict[str, Any] = {
            "market": market,
            "side": side,
            "ord_type": ord_type,
        }
        if volume is not None:
            params["volume"] = str(volume)
        if price is not None:
            params["price"] = str(price)

        headers = await self._build_auth_headers(params)
        return await self._request_json(
            "POST",
            "/orders",
            json_body=params,
            headers=headers,
            retry_safe=False,
        )

    async def cancel_order(self, uuid_: str) -> dict:
        """주문 취소."""
        params = {"uuid": uuid_}
        headers = await self._build_auth_headers(params)
        return await self._request_json(
            "DELETE",
            "/order",
            params=params,
            headers=headers,
            retry_safe=True,
        )

    async def get_order(self, uuid_: str) -> dict:
        """주문 상태 조회."""
        params = {"uuid": uuid_}
        headers = await self._build_auth_headers(params)
        return await self._request_json(
            "GET",
            "/order",
            params=params,
            headers=headers,
            retry_safe=True,
        )

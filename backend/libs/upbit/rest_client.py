from __future__ import annotations
"""pyupbit 래퍼 - REST API 클라이언트"""
import asyncio
import hashlib
import jwt
import uuid
from typing import Any
from urllib.parse import urlencode

import httpx
import pyupbit

from libs.config import get_settings

UPBIT_REST_BASE = "https://api.upbit.com/v1"


class UpbitRestClient:
    """
    업비트 REST API 클라이언트.
    - pyupbit 활용 (공개 API)
    - 인증 API는 직접 JWT 발급
    """

    def __init__(self):
        settings = get_settings()
        self.access_key = settings.upbit_access_key
        self.secret_key = settings.upbit_secret_key

    def _generate_token(self, query_params: dict | None = None) -> str:
        payload = {
            "access_key": self.access_key,
            "nonce": str(uuid.uuid4()),
        }
        if query_params:
            query_string = urlencode(query_params).encode()
            m = hashlib.sha512()
            m.update(query_string)
            payload["query_hash"] = m.hexdigest()
            payload["query_hash_alg"] = "SHA512"

        return jwt.encode(payload, self.secret_key, algorithm="HS256")

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
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{UPBIT_REST_BASE}/ticker",
                params={"markets": market},
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                return float(data[0]["trade_price"])
            return None

    async def get_balances(self) -> list[dict]:
        """계좌 잔고 조회."""
        headers = {"Authorization": f"Bearer {self._generate_token()}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{UPBIT_REST_BASE}/accounts", headers=headers)
            resp.raise_for_status()
            return resp.json()

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

        headers = {"Authorization": f"Bearer {self._generate_token(params)}"}
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{UPBIT_REST_BASE}/orders",
                json=params,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def cancel_order(self, uuid_: str) -> dict:
        """주문 취소."""
        params = {"uuid": uuid_}
        headers = {"Authorization": f"Bearer {self._generate_token(params)}"}
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{UPBIT_REST_BASE}/order",
                params=params,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_order(self, uuid_: str) -> dict:
        """주문 상태 조회."""
        params = {"uuid": uuid_}
        headers = {"Authorization": f"Bearer {self._generate_token(params)}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{UPBIT_REST_BASE}/order",
                params=params,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()

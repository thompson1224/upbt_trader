from __future__ import annotations
"""전략 서비스 - 1분봉 수신 → 지표 계산 → Fear&Greed 감성 → 추세 필터 → 신호 생성"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta

import redis.asyncio as aioredis

from sqlalchemy import select, desc, func

from libs.config import get_settings
from libs.db.session import get_session_factory
from libs.db.models import Coin, Candle1m, IndicatorSnapshot, SentimentSnapshot, Signal
from libs.ai.fear_greed_client import FearGreedClient
from apps.strategy_service.indicators.calculator import compute_indicators
from apps.strategy_service.fusion.signal_fusion import fuse_signals

import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STRATEGY_ID = "hybrid_v1"
TIMEFRAME = "1m"
CANDLE_WINDOW = 200          # 지표 계산에 필요한 캔들 수
TOP_MARKETS_BY_VOLUME = 10   # 24h 거래량 상위 N개 코인만 처리

# 1시간봉 추세 필터: EMA12/EMA30 비율 기준
HOURLY_CANDLES = 60          # 1분봉 60개 = 1시간
TREND_BAND = 0.002           # 0.2% 이내는 횡보로 판단


class StrategyRunner:
    def __init__(self):
        self.settings = get_settings()
        self.fear_greed = FearGreedClient()
        self.session_factory = get_session_factory()
        self._redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        self._redis: aioredis.Redis | None = None
        self._last_signal: dict[str, str] = {}
        self._signal_streak: dict[str, int] = {}

    async def _get_redis(self) -> aioredis.Redis:
        """Redis 클라이언트 반환. stale 연결이면 재생성."""
        try:
            if self._redis:
                await self._redis.ping()
                return self._redis
        except Exception:
            logger.warning("Strategy Redis connection stale, reconnecting...")
            self._redis = None
        self._redis = aioredis.from_url(self._redis_url)
        return self._redis

    async def run(self):
        logger.info("Strategy service started. strategy=%s", STRATEGY_ID)
        while True:
            try:
                await self._process_all_markets()
            except Exception as e:
                logger.error("Strategy loop error: %s", e)
            await asyncio.sleep(60)  # 1분 주기

    async def _process_all_markets(self):
        async with self.session_factory() as db:
            cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)
            vol_subq = (
                select(
                    Candle1m.coin_id,
                    func.sum(Candle1m.value).label("vol_24h"),
                )
                .where(Candle1m.ts >= cutoff)
                .group_by(Candle1m.coin_id)
                .order_by(desc("vol_24h"))
                .limit(TOP_MARKETS_BY_VOLUME)
                .subquery()
            )
            result = await db.execute(
                select(Coin)
                .join(vol_subq, Coin.id == vol_subq.c.coin_id)
                .where(Coin.is_active == True)
                .order_by(desc(vol_subq.c.vol_24h))
            )
            coins = result.scalars().all()

        logger.info("Processing top %d markets by 24h volume", len(coins))

        # Fear & Greed는 전 코인 공통 (하루 1회 업데이트, 1시간 캐시)
        sentiment_score, sentiment_conf = await self.fear_greed.get_sentiment()

        batch_size = 5
        for i in range(0, len(coins), batch_size):
            batch = coins[i : i + batch_size]
            results = await asyncio.gather(
                *[self._process_coin(coin, sentiment_score, sentiment_conf) for coin in batch],
                return_exceptions=True,
            )
            for coin, result in zip(batch, results):
                if isinstance(result, Exception):
                    logger.error("Coin processing error [%s]: %s", coin.market, result)
            if i + batch_size < len(coins):
                await asyncio.sleep(3)  # Groq 제거로 딜레이 단축 가능

    async def _process_coin(self, coin: Coin, sentiment_score: float, sentiment_conf: float):
        async with self.session_factory() as db:
            result = await db.execute(
                select(Candle1m)
                .where(Candle1m.coin_id == coin.id)
                .order_by(desc(Candle1m.ts))
                .limit(CANDLE_WINDOW)
            )
            candles = list(reversed(result.scalars().all()))

        if len(candles) < 50:
            return

        df = pd.DataFrame([
            {
                "ts": c.ts, "open": c.open, "high": c.high,
                "low": c.low, "close": c.close,
                "volume": c.volume, "value": c.value,
            }
            for c in candles
        ])

        # 기술적 지표 계산
        ind = compute_indicators(df)

        # 지표 스냅샷 저장
        async with self.session_factory() as db:
            snapshot = IndicatorSnapshot(
                coin_id=coin.id,
                timeframe=TIMEFRAME,
                ts=datetime.now(tz=timezone.utc),
                rsi=ind.rsi,
                macd=ind.macd,
                macd_signal=ind.macd_signal,
                macd_hist=ind.macd_hist,
                bb_upper=ind.bb_upper,
                bb_mid=ind.bb_mid,
                bb_lower=ind.bb_lower,
                bb_pct=ind.bb_pct,
                ema_20=ind.ema_20,
                ema_50=ind.ema_50,
                ta_score=ind.ta_score,
            )
            db.add(snapshot)
            await db.commit()

        # Phase 3: 1시간봉 추세 필터
        hourly_trend = _compute_hourly_trend(df)

        # 신호 융합
        signal = fuse_signals(
            ta_score=ind.ta_score,
            sentiment_score=sentiment_score,
            sentiment_confidence=sentiment_conf,
        )

        # hold 신호는 항상 저장 생략 (노이즈 제거, UI 정리)
        if signal.side == "hold":
            self._last_signal[coin.market] = "hold"
            self._signal_streak[coin.market] = 0
            return

        # Phase 3: 추세 역행 신호 차단
        if signal.side == "buy" and hourly_trend == "downtrend":
            logger.debug("Buy signal blocked by downtrend filter: %s", coin.market)
            return
        if signal.side == "sell" and hourly_trend == "uptrend":
            logger.debug("Sell signal blocked by uptrend filter: %s", coin.market)
            return

        # 신호 저장
        current_price = float(df["close"].iloc[-1])
        stop_loss = current_price * (1 - 0.03) if signal.side == "buy" else None
        take_profit = current_price * (1 + 0.06) if signal.side == "buy" else None

        async with self.session_factory() as db:
            db_signal = Signal(
                strategy_id=STRATEGY_ID,
                coin_id=coin.id,
                timeframe=TIMEFRAME,
                ts=datetime.now(tz=timezone.utc),
                ta_score=signal.ta_score,
                sentiment_score=signal.sentiment_score,
                final_score=signal.final_score,
                confidence=signal.confidence,
                side=signal.side,
                status="new",
                suggested_stop_loss=stop_loss,
                suggested_take_profit=take_profit,
            )
            db.add(db_signal)
            await db.commit()

        logger.info(
            "Signal generated: %s %s score=%.2f conf=%.2f trend=%s",
            coin.market, signal.side, signal.final_score,
            signal.confidence, hourly_trend,
        )

        # Redis로 신호 브로드캐스트
        try:
            r = await self._get_redis()
            await r.publish("upbit:signal", json.dumps({
                "id": db_signal.id,
                "market": coin.market,
                "coinId": coin.id,
                "side": signal.side,
                "taScore": signal.ta_score,
                "sentimentScore": signal.sentiment_score,
                "finalScore": signal.final_score,
                "confidence": signal.confidence,
                "trend": hourly_trend,
                "ts": datetime.now(tz=timezone.utc).isoformat(),
            }))
        except Exception as e:
            logger.warning("Failed to publish signal to Redis: %s", e)

        # Fear & Greed 감성 DB 저장 (코인별 1회 공통 저장 — 첫 신호 발행 시)
        try:
            async with self.session_factory() as db:
                snap = SentimentSnapshot(
                    coin_id=coin.id,
                    ts=datetime.now(tz=timezone.utc),
                    source="fear_greed",
                    sentiment_score=sentiment_score,
                    confidence=sentiment_conf,
                    model_version="alternative.me/fng/v1",
                    summary=f"Fear&Greed index ~{self.fear_greed.last_index_value}",
                    keywords=None,
                )
                db.add(snap)
                await db.commit()
        except Exception as e:
            logger.warning("Sentiment snapshot save failed: %s", e)


def _compute_hourly_trend(df: pd.DataFrame) -> str:
    """
    최근 60개 1분봉의 EMA12/EMA30으로 1시간봉 추세 판단.
    Returns: "uptrend" | "downtrend" | "sideways"
    """
    close = df["close"]
    n = len(close)
    if n < HOURLY_CANDLES:
        return "sideways"

    recent = close.iloc[-HOURLY_CANDLES:]
    ema_fast = float(recent.ewm(span=12, adjust=False).mean().iloc[-1])
    ema_slow = float(recent.ewm(span=30, adjust=False).mean().iloc[-1])

    if ema_slow == 0:
        return "sideways"

    ratio = (ema_fast - ema_slow) / ema_slow
    if ratio > TREND_BAND:
        return "uptrend"
    elif ratio < -TREND_BAND:
        return "downtrend"
    return "sideways"


async def main():
    runner = StrategyRunner()
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())

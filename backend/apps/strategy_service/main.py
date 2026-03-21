from __future__ import annotations
"""전략 서비스 - 1분봉 수신 → 지표 계산 → Claude 감성 → 신호 생성"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, desc

from libs.config import get_settings
from libs.db.session import get_session_factory
from libs.db.models import Coin, Candle1m, IndicatorSnapshot, SentimentSnapshot, Signal
from libs.ai.claude_client import ClaudeClient
from apps.strategy_service.indicators.calculator import compute_indicators
from apps.strategy_service.fusion.signal_fusion import fuse_signals
from apps.risk_service.guards.pre_trade_guard import PositionSizer

import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STRATEGY_ID = "hybrid_v1"
TIMEFRAME = "1m"
CANDLE_WINDOW = 200          # 지표 계산에 필요한 캔들 수
SENTIMENT_INTERVAL_SEC = 600  # 10분마다 감성 분석
MIN_CONFIDENCE = 0.5


class StrategyRunner:
    def __init__(self):
        self.settings = get_settings()
        self.claude = ClaudeClient()
        self.session_factory = get_session_factory()
        self._sentiment_cache: dict[str, tuple[float, float, datetime]] = {}
        # market -> (score, confidence, updated_at)

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
            # 활성 코인 목록
            result = await db.execute(
                select(Coin).where(Coin.is_active == True)
            )
            coins = result.scalars().all()

        logger.info("Processing %d markets", len(coins))

        # 코인별 병렬 처리 (최대 10개씩 배치)
        batch_size = 10
        for i in range(0, len(coins), batch_size):
            batch = coins[i : i + batch_size]
            await asyncio.gather(
                *[self._process_coin(coin) for coin in batch],
                return_exceptions=True,
            )

    async def _process_coin(self, coin: Coin):
        async with self.session_factory() as db:
            # 최근 캔들 조회
            result = await db.execute(
                select(Candle1m)
                .where(Candle1m.coin_id == coin.id)
                .order_by(desc(Candle1m.ts))
                .limit(CANDLE_WINDOW)
            )
            candles = list(reversed(result.scalars().all()))

        if len(candles) < 50:
            return  # 데이터 부족

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

        # 감성 분석 (10분 캐시)
        sentiment_score, sentiment_conf = await self._get_sentiment(coin, df, ind)

        # 신호 융합
        signal = fuse_signals(
            ta_score=ind.ta_score,
            sentiment_score=sentiment_score,
            sentiment_confidence=sentiment_conf,
        )

        # hold 신호는 저장 생략
        if signal.side == "hold" and abs(signal.final_score) < 0.2:
            return

        # 신호 저장
        current_price = float(df["close"].iloc[-1])
        sizer = PositionSizer()
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
            "Signal generated: %s %s score=%.2f conf=%.2f ta_only=%s",
            coin.market, signal.side, signal.final_score,
            signal.confidence, signal.ta_only_mode,
        )

    async def _get_sentiment(
        self, coin: Coin, df: pd.DataFrame, ind
    ) -> tuple[float | None, float | None]:
        """캐시된 감성 점수 반환, 만료 시 Claude API 호출."""
        now = datetime.now(tz=timezone.utc)
        cached = self._sentiment_cache.get(coin.market)

        if cached:
            score, conf, updated_at = cached
            if (now - updated_at).total_seconds() < SENTIMENT_INTERVAL_SEC:
                return score, conf

        # Claude API 호출
        current_price = float(df["close"].iloc[-1])
        price_change = float(df["close"].pct_change(24).iloc[-1]) * 100

        ta_context = (
            f"RSI: {ind.rsi:.1f}" if ind.rsi else ""
        )
        if ind.macd_hist:
            ta_context += f", MACD_hist: {ind.macd_hist:.4f}"
        if ind.bb_pct:
            ta_context += f", BB%B: {ind.bb_pct:.2f}"

        result = await self.claude.analyze_sentiment(
            market=coin.market,
            current_price=current_price,
            price_change_24h=price_change,
            volume_24h=float(df["value"].tail(1440).sum()),
            ta_context=ta_context,
        )

        if result is None:
            return None, None

        # 캐시 저장
        self._sentiment_cache[coin.market] = (
            result["sentiment_score"],
            result["confidence"],
            now,
        )

        # DB 저장
        async with self.session_factory() as db:
            snap = SentimentSnapshot(
                coin_id=coin.id,
                ts=now,
                source="claude",
                sentiment_score=result["sentiment_score"],
                confidence=result["confidence"],
                model_version=self.settings.claude_model,
                summary=result.get("summary"),
                keywords=str(result.get("keywords", [])),
            )
            db.add(snap)
            await db.commit()

        return result["sentiment_score"], result["confidence"]


async def main():
    runner = StrategyRunner()
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())

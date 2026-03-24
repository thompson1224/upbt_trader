"""Crypto Fear & Greed Index 클라이언트 (api.alternative.me/fng/)"""
from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta

import httpx

logger = logging.getLogger(__name__)

_FNG_URL = "https://api.alternative.me/fng/"
_CACHE_TTL_SEC = 3600  # 1시간 캐시 (지수는 하루 1회 업데이트)


class FearGreedClient:
    """
    Crypto Fear & Greed Index를 감성 점수로 변환.
    - 지수 0~25 (극단 공포) → 강한 매수 신호 (contrarian)
    - 지수 76~100 (극단 탐욕) → 강한 매도 신호 (contrarian)
    - 지수 40~60 (중립) → 신호 없음
    """

    def __init__(self) -> None:
        self._cached: tuple[float, float, datetime] | None = None
        # (score, confidence, fetched_at)

    async def get_sentiment(self) -> tuple[float, float]:
        """
        Returns:
            (sentiment_score, confidence) — score -1~1, confidence 0~1
        """
        now = datetime.now(tz=timezone.utc)
        if self._cached:
            score, conf, fetched_at = self._cached
            if (now - fetched_at).total_seconds() < _CACHE_TTL_SEC:
                return score, conf

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(_FNG_URL, params={"limit": 1})
                resp.raise_for_status()
                value = int(resp.json()["data"][0]["value"])
        except Exception as e:
            logger.warning("Fear & Greed API error: %s", e)
            if self._cached:
                score, conf, _ = self._cached
                return score, conf  # 만료된 캐시라도 사용
            return 0.0, 0.3  # 완전 실패 시 중립 반환

        score = _index_to_score(value)
        conf = _index_to_confidence(value)
        self._cached = (score, conf, now)
        logger.info("Fear & Greed index=%d → score=%.2f conf=%.2f", value, score, conf)
        return score, conf

    @property
    def last_index_value(self) -> int | None:
        """마지막으로 조회된 지수 원본값 (0~100)."""
        if self._cached:
            score, _, _ = self._cached
            return _score_to_approx_index(score)
        return None


def _index_to_score(value: int) -> float:
    """
    Fear & Greed Index (0~100) → sentiment score (-1~1).
    역발상(contrarian) 전략: 극단 공포 = 매수 기회, 극단 탐욕 = 매도 기회.
    """
    if value <= 25:
        # 극단 공포: 0→+0.8, 25→+0.2
        return round((25 - value) / 25 * 0.8, 3)
    elif value >= 75:
        # 극단 탐욕: 75→-0.2, 100→-0.8
        return round(-((value - 75) / 25 * 0.8), 3)
    elif value < 40:
        # 공포 구간: 25→+0.2, 40→0
        return round((40 - value) / 15 * 0.2, 3)
    elif value > 60:
        # 탐욕 구간: 60→0, 75→-0.2
        return round(-((value - 60) / 15 * 0.2), 3)
    else:
        return 0.0  # 40~60 완전 중립


def _index_to_confidence(value: int) -> float:
    """지수가 극단에 가까울수록 높은 신뢰도."""
    distance_from_neutral = abs(value - 50)
    return round(min(0.85, 0.45 + distance_from_neutral / 50 * 0.4), 2)


def _score_to_approx_index(score: float) -> int:
    """역변환 (근사값, 로그 목적)."""
    return int(50 - score * 50)

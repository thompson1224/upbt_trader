from __future__ import annotations
from typing import Optional
"""TA 점수 + LLM 감성 점수 융합 → 최종 신호 생성"""
from dataclasses import dataclass
from typing import Literal

TA_WEIGHT = 0.6
SENTIMENT_WEIGHT = 0.4

BUY_THRESHOLD = 0.25    # 완만한 상승 추세도 포착 (기존 0.35)
SELL_THRESHOLD = -0.25  # 기존 -0.35
MIN_CONFIDENCE = 0.45   # Ollama 보수적 출력 대응 (기존 0.5)


@dataclass
class FusedSignal:
    side: Literal["buy", "sell", "hold"]
    ta_score: float
    sentiment_score: Optional[float]
    final_score: float
    confidence: float
    ta_only_mode: bool  # LLM 폴백 여부


def fuse_signals(
    ta_score: float,
    ta_confidence: float = 1.0,
    sentiment_score: Optional[float] = None,
    sentiment_confidence: Optional[float] = None,
) -> FusedSignal:
    """
    기술적 지표 점수와 감성 점수를 융합하여 최종 신호를 생성합니다.

    감성 분석 실패 시 TA-only 모드로 폴백.
    """
    ta_only_mode = sentiment_score is None

    if ta_only_mode:
        final_score = ta_score
        confidence = ta_confidence
    else:
        s_conf = sentiment_confidence or 0.5
        # 신뢰도 가중 융합
        ta_w = TA_WEIGHT * ta_confidence
        sent_w = SENTIMENT_WEIGHT * s_conf
        total_w = ta_w + sent_w

        final_score = (ta_w * ta_score + sent_w * sentiment_score) / total_w
        confidence = total_w / (TA_WEIGHT + SENTIMENT_WEIGHT)

    # 신뢰도 미달 시 홀드
    if confidence < MIN_CONFIDENCE:
        side = "hold"
    elif final_score >= BUY_THRESHOLD:
        side = "buy"
    elif final_score <= SELL_THRESHOLD:
        side = "sell"
    else:
        side = "hold"

    return FusedSignal(
        side=side,
        ta_score=ta_score,
        sentiment_score=sentiment_score,
        final_score=final_score,
        confidence=confidence,
        ta_only_mode=ta_only_mode,
    )

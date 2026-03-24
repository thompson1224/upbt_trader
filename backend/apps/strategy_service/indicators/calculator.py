"""기술적 지표 계산 모듈 - RSI, MACD, 볼린저밴드, EMA"""
from __future__ import annotations
from typing import Optional
import pandas as pd
import numpy as np
from dataclasses import dataclass


@dataclass
class IndicatorResult:
    rsi: Optional[float]
    macd: Optional[float]
    macd_signal: Optional[float]
    macd_hist: Optional[float]
    bb_upper: Optional[float]
    bb_mid: Optional[float]
    bb_lower: Optional[float]
    bb_pct: float | None  # %B position
    ema_20: Optional[float]
    ema_50: Optional[float]
    ta_score: float  # -1 ~ 1


def compute_indicators(df: pd.DataFrame) -> IndicatorResult:
    """
    OHLCV 데이터프레임에서 기술적 지표 계산.
    df columns: open, high, low, close, volume
    """
    close = df["close"]
    n = len(close)

    rsi = _calc_rsi(close) if n >= 15 else None
    macd, macd_signal, macd_hist = _calc_macd(close) if n >= 35 else (None, None, None)
    bb_upper, bb_mid, bb_lower, bb_pct = _calc_bollinger(close) if n >= 20 else (None, None, None, None)
    ema_20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1]) if n >= 20 else None
    ema_50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1]) if n >= 50 else None

    volume = df["volume"] if "volume" in df.columns else None
    ta_score = _compute_ta_score(rsi, macd, macd_hist, bb_pct, close, ema_20, ema_50, volume)

    return IndicatorResult(
        rsi=rsi,
        macd=macd,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
        bb_upper=bb_upper,
        bb_mid=bb_mid,
        bb_lower=bb_lower,
        bb_pct=bb_pct,
        ema_20=ema_20,
        ema_50=ema_50,
        ta_score=ta_score,
    )


def _calc_rsi(close: pd.Series, period: int = 14) -> float | None:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if not np.isnan(val) else None


def _calc_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[float | None, float | None, float | None]:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line

    def safe(s: pd.Series) -> float | None:
        v = s.iloc[-1]
        return float(v) if not np.isnan(v) else None

    return safe(macd_line), safe(signal_line), safe(hist)


def _calc_bollinger(
    close: pd.Series, period: int = 20, num_std: float = 2.0
) -> tuple[float | None, float | None, float | None, float | None]:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std

    m = float(mid.iloc[-1])
    u = float(upper.iloc[-1])
    l = float(lower.iloc[-1])
    c = float(close.iloc[-1])

    if any(np.isnan(x) for x in [m, u, l]):
        return None, None, None, None

    bb_pct = (c - l) / (u - l) if (u - l) > 0 else 0.5
    return u, m, l, float(bb_pct)


def _compute_ta_score(
    rsi: float | None,
    macd: float | None,
    macd_hist: float | None,
    bb_pct: float | None,
    close: pd.Series,
    ema_20: float | None,
    ema_50: float | None,
    volume: pd.Series | None = None,
) -> float:
    """
    복합 TA 점수 계산 (-1 ~ 1).
    - RSI: 과매도(+), 과매수(-) 신호
    - MACD: 히스토그램 방향성
    - BB: %B 위치
    - EMA: 추세 방향
    """
    scores = []

    # RSI (30이하 매수, 70이상 매도; 40~60 완전 중립)
    if rsi is not None:
        if rsi < 30:
            scores.append(min(1.0, (30 - rsi) / 30))
        elif rsi > 70:
            scores.append(-min(1.0, (rsi - 70) / 30))
        elif rsi < 40:
            scores.append((40 - rsi) / 40 * 0.5)
        elif rsi > 60:
            scores.append(-((rsi - 60) / 40 * 0.5))
        else:
            scores.append(0.0)  # 40~60 완전 중립, 노이즈 제거

    # MACD 히스토그램
    if macd_hist is not None and macd is not None:
        score = np.tanh(macd_hist / (abs(macd) + 1e-8))
        scores.append(float(score))

    # Bollinger %B
    if bb_pct is not None:
        if bb_pct < 0.2:
            scores.append(0.5)  # 하단 밴드 근처 = 매수 신호
        elif bb_pct > 0.8:
            scores.append(-0.5)  # 상단 밴드 근처 = 매도 신호
        else:
            scores.append(0.0)

    # EMA 추세
    if ema_20 is not None and ema_50 is not None:
        current = float(close.iloc[-1])
        if ema_20 > ema_50 and current > ema_20:
            scores.append(0.4)  # 상승 추세
        elif ema_20 < ema_50 and current < ema_20:
            scores.append(-0.4)  # 하락 추세

    if not scores:
        return 0.0

    raw = float(np.mean(scores))

    # 거래량 확인 필터: 현재 거래량이 20개 이동평균의 0.8배 미만이면 신호 감쇄
    if volume is not None and len(volume) >= 20:
        avg_vol = float(volume.rolling(20).mean().iloc[-1])
        cur_vol = float(volume.iloc[-1])
        if avg_vol > 0:
            vol_ratio = cur_vol / avg_vol
            multiplier = float(np.clip(vol_ratio / 0.8, 0.5, 1.5))
            raw = raw * multiplier

    return float(np.clip(raw, -1.0, 1.0))

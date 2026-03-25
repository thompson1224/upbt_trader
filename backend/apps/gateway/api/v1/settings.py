from __future__ import annotations
"""API 키 및 자동매매 설정 관리"""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from cryptography.fernet import Fernet

from libs.audit import record_audit_event
from libs.config import get_settings
from libs.db.models import RuntimeState
from libs.db.session import get_session_factory

router = APIRouter()

UPBIT_ACCESS_KEY_REDIS_KEY = "secret:upbit:access"
UPBIT_SECRET_KEY_REDIS_KEY = "secret:upbit:secret"
AUTO_TRADE_REDIS_KEY = "auto_trade:enabled"
EXTERNAL_POSITION_SL_REDIS_KEY = "settings:external_position_sl:enabled"
MANUAL_TEST_MODE_REDIS_KEY = "settings:manual_test_mode:enabled"
MIN_BUY_FINAL_SCORE_REDIS_KEY = "settings:min_buy_final_score"
HOLD_STALE_MINUTES_REDIS_KEY = "settings:hold_stale_minutes"
EXCLUDED_MARKETS_REDIS_KEY = "settings:excluded_markets"
RISK_LOSS_STREAK_REDIS_KEY = "risk:loss_streak"
RISK_LOSS_STREAK_DATE_REDIS_KEY = "risk:loss_streak:date"
RUNTIME_STATE_LOSS_STREAK_KEY = "risk.loss_streak"
RUNTIME_STATE_LOSS_STREAK_DATE_KEY = "risk.loss_streak.date"


def _get_redis():
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    return aioredis.from_url(redis_url)


def _get_fernet() -> Fernet:
    key = os.environ.get("ENCRYPTION_KEY", "")
    if not key:
        raise HTTPException(500, "Encryption key not configured")
    return Fernet(key.encode())


def _risk_metric_date(now: datetime | None = None) -> str:
    kst = ZoneInfo("Asia/Seoul")
    ts = now.astimezone(kst) if now else datetime.now(tz=kst)
    return ts.strftime("%Y%m%d")


async def _persist_runtime_state_values(values: dict[str, str]) -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        for key, value in values.items():
            state = await db.get(RuntimeState, key)
            if state is None:
                db.add(RuntimeState(key=key, value=value))
            else:
                state.value = value
        await db.commit()


# ── 요청 스키마 ─────────────────────────────────────────────

class UpbitKeyRequest(BaseModel):
    access_key: str
    secret_key: str


class GroqKeyRequest(BaseModel):
    api_key: str


class AutoTradeRequest(BaseModel):
    enabled: bool


class ExternalPositionProtectionRequest(BaseModel):
    enabled: bool


class ManualTestModeRequest(BaseModel):
    enabled: bool


class MinBuyFinalScoreRequest(BaseModel):
    value: float


class HoldStaleMinutesRequest(BaseModel):
    value: int


class ExcludedMarketsRequest(BaseModel):
    markets: list[str]


# ── Upbit API 키 ────────────────────────────────────────────

@router.post("/secrets/upbit-keys", status_code=204)
async def set_upbit_keys(req: UpbitKeyRequest):
    """업비트 API 키 저장 (암호화)."""
    f = _get_fernet()
    encrypted_access = f.encrypt(req.access_key.encode()).decode()
    encrypted_secret = f.encrypt(req.secret_key.encode()).decode()
    r = _get_redis()
    try:
        await r.set(UPBIT_ACCESS_KEY_REDIS_KEY, encrypted_access)
        await r.set(UPBIT_SECRET_KEY_REDIS_KEY, encrypted_secret)
    finally:
        await r.aclose()

    # 현재 프로세스의 즉시 사용성은 유지하되, 실제 주문 서비스는 Redis 저장값을 우선 사용한다.
    os.environ["UPBIT_ACCESS_KEY"] = req.access_key
    os.environ["UPBIT_SECRET_KEY"] = req.secret_key
    await record_audit_event(
        event_type="upbit_keys_updated",
        source="settings",
        message="Upbit API keys updated",
        payload={"access_key_set": bool(req.access_key), "secret_key_set": bool(req.secret_key)},
    )
    return None


# ── Groq API 키 ─────────────────────────────────────────────

@router.post("/secrets/groq-key", status_code=204)
async def set_groq_key(req: GroqKeyRequest):
    """Groq API 키 저장 (런타임 환경변수 업데이트). 반영은 서비스 재시작 필요."""
    os.environ["GROQ_API_KEY"] = req.api_key
    await record_audit_event(
        event_type="groq_key_updated",
        source="settings",
        message="Groq API key updated",
        payload={"api_key_set": bool(req.api_key)},
    )
    return None


# ── 자동매매 ON/OFF ─────────────────────────────────────────

@router.patch("/settings/auto-trade")
async def set_auto_trade(req: AutoTradeRequest):
    """자동매매 ON/OFF 설정을 Redis에 저장."""
    r = _get_redis()
    try:
        await r.set(AUTO_TRADE_REDIS_KEY, "1" if req.enabled else "0")
    finally:
        await r.aclose()
    await record_audit_event(
        event_type="auto_trade_toggled",
        source="settings",
        message=f"Auto-trade {'enabled' if req.enabled else 'disabled'}",
        payload={"enabled": req.enabled},
    )
    return {"enabled": req.enabled}


@router.get("/settings/auto-trade")
async def get_auto_trade():
    """현재 자동매매 ON/OFF 상태 반환. 키 부재 시 기본값 True."""
    r = _get_redis()
    try:
        val = await r.get(AUTO_TRADE_REDIS_KEY)
    finally:
        await r.aclose()
    enabled = (val is None) or (val.decode() == "1")
    return {"enabled": enabled}


@router.patch("/settings/external-position-stop-loss")
async def set_external_position_stop_loss(req: ExternalPositionProtectionRequest):
    """외부 보유분 자동 손절 ON/OFF 설정. 기본값은 OFF."""
    r = _get_redis()
    try:
        await r.set(EXTERNAL_POSITION_SL_REDIS_KEY, "1" if req.enabled else "0")
    finally:
        await r.aclose()
    await record_audit_event(
        event_type="external_position_stop_loss_toggled",
        source="settings",
        message=f"External position stop-loss {'enabled' if req.enabled else 'disabled'}",
        payload={"enabled": req.enabled},
    )
    return {"enabled": req.enabled}


@router.get("/settings/external-position-stop-loss")
async def get_external_position_stop_loss():
    """외부 보유분 자동 손절 ON/OFF 상태 반환. 키 부재 시 기본값 False."""
    r = _get_redis()
    try:
        val = await r.get(EXTERNAL_POSITION_SL_REDIS_KEY)
    finally:
        await r.aclose()
    enabled = (val is not None) and (val.decode() == "1")
    return {"enabled": enabled}


@router.patch("/settings/manual-test-mode")
async def set_manual_test_mode(req: ManualTestModeRequest):
    """수동 주문 테스트 모드 ON/OFF 설정. 기본값은 OFF."""
    r = _get_redis()
    try:
        await r.set(MANUAL_TEST_MODE_REDIS_KEY, "1" if req.enabled else "0")
    finally:
        await r.aclose()
    await record_audit_event(
        event_type="manual_test_mode_toggled",
        source="settings",
        message=f"Manual test mode {'enabled' if req.enabled else 'disabled'}",
        payload={"enabled": req.enabled},
    )
    return {"enabled": req.enabled}


@router.get("/settings/manual-test-mode")
async def get_manual_test_mode():
    """수동 주문 테스트 모드 상태 반환. 키 부재 시 기본값 False."""
    r = _get_redis()
    try:
        val = await r.get(MANUAL_TEST_MODE_REDIS_KEY)
    finally:
        await r.aclose()
    enabled = (val is not None) and (val.decode() == "1")
    return {"enabled": enabled}


@router.patch("/settings/min-buy-final-score")
async def set_min_buy_final_score(req: MinBuyFinalScoreRequest):
    """매수 최소 final score 설정. 기본값 0.0 = 비활성."""
    if req.value < 0 or req.value > 1:
        raise HTTPException(status_code=400, detail="value must be between 0 and 1")
    normalized = round(req.value, 4)
    r = _get_redis()
    try:
        await r.set(MIN_BUY_FINAL_SCORE_REDIS_KEY, str(normalized))
    finally:
        await r.aclose()
    await record_audit_event(
        event_type="min_buy_final_score_updated",
        source="settings",
        message=f"Minimum buy final score set to {normalized:.2f}",
        payload={"value": normalized},
    )
    return {"value": normalized}


@router.get("/settings/min-buy-final-score")
async def get_min_buy_final_score():
    """매수 최소 final score 조회. 키 부재 시 기본값 0.0."""
    r = _get_redis()
    try:
        val = await r.get(MIN_BUY_FINAL_SCORE_REDIS_KEY)
    finally:
        await r.aclose()
    value = float(val.decode()) if val is not None else 0.0
    return {"value": value}


@router.patch("/settings/hold-stale-minutes")
async def set_hold_stale_minutes(req: HoldStaleMinutesRequest):
    """장기 hold 경고 기준(분) 설정."""
    if req.value < 30 or req.value > 1440:
        raise HTTPException(status_code=400, detail="value must be between 30 and 1440")
    normalized = int(req.value)
    r = _get_redis()
    try:
        await r.set(HOLD_STALE_MINUTES_REDIS_KEY, str(normalized))
    finally:
        await r.aclose()
    await record_audit_event(
        event_type="hold_stale_minutes_updated",
        source="settings",
        message=f"Hold stale threshold set to {normalized} minutes",
        payload={"value": normalized},
    )
    return {"value": normalized}


@router.get("/settings/hold-stale-minutes")
async def get_hold_stale_minutes():
    """장기 hold 경고 기준 조회. 키 부재 시 환경 기본값 사용."""
    r = _get_redis()
    try:
        val = await r.get(HOLD_STALE_MINUTES_REDIS_KEY)
    finally:
        await r.aclose()
    if val is not None:
        return {"value": int(val.decode())}
    return {"value": int(get_settings().risk_hold_stale_minutes)}


@router.patch("/settings/excluded-markets")
async def set_excluded_markets(req: ExcludedMarketsRequest):
    normalized = sorted({
        market.strip().upper()
        for market in req.markets
        if isinstance(market, str) and market.strip()
    })
    r = _get_redis()
    try:
        await r.set(EXCLUDED_MARKETS_REDIS_KEY, json.dumps(normalized))
    finally:
        await r.aclose()
    await record_audit_event(
        event_type="excluded_markets_updated",
        source="settings",
        message=f"Excluded markets updated ({len(normalized)} markets)",
        payload={"markets": normalized},
    )
    return {"markets": normalized}


@router.get("/settings/excluded-markets")
async def get_excluded_markets():
    r = _get_redis()
    try:
        val = await r.get(EXCLUDED_MARKETS_REDIS_KEY)
    finally:
        await r.aclose()
    if val is None:
        return {"markets": []}
    return {"markets": json.loads(val.decode())}


@router.post("/settings/risk/reset-loss-streak")
async def reset_loss_streak():
    """연속 손실 횟수를 즉시 0으로 초기화."""
    current_date = _risk_metric_date()
    r = _get_redis()
    try:
        await r.set(RISK_LOSS_STREAK_REDIS_KEY, "0")
        await r.set(RISK_LOSS_STREAK_DATE_REDIS_KEY, current_date)
    finally:
        await r.aclose()

    await _persist_runtime_state_values({
        RUNTIME_STATE_LOSS_STREAK_KEY: "0",
        RUNTIME_STATE_LOSS_STREAK_DATE_KEY: current_date,
    })
    await record_audit_event(
        event_type="loss_streak_reset",
        source="settings",
        message="Loss streak reset",
        payload={"loss_streak": 0, "streak_date": current_date},
    )
    return {"lossStreak": 0, "streakDate": current_date}

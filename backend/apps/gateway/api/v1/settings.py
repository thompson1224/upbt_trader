from __future__ import annotations
"""API 키 및 자동매매 설정 관리"""
import os

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from cryptography.fernet import Fernet

from libs.audit import record_audit_event

router = APIRouter()

UPBIT_ACCESS_KEY_REDIS_KEY = "secret:upbit:access"
UPBIT_SECRET_KEY_REDIS_KEY = "secret:upbit:secret"
AUTO_TRADE_REDIS_KEY = "auto_trade:enabled"
EXTERNAL_POSITION_SL_REDIS_KEY = "settings:external_position_sl:enabled"
MANUAL_TEST_MODE_REDIS_KEY = "settings:manual_test_mode:enabled"


def _get_redis():
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    return aioredis.from_url(redis_url)


def _get_fernet() -> Fernet:
    key = os.environ.get("ENCRYPTION_KEY", "")
    if not key:
        raise HTTPException(500, "Encryption key not configured")
    return Fernet(key.encode())


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

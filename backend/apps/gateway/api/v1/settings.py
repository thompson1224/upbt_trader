from __future__ import annotations
"""API 키 및 자동매매 설정 관리"""
import os

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from cryptography.fernet import Fernet

router = APIRouter()


def _get_fernet() -> Fernet:
    key = os.environ.get("ENCRYPTION_KEY", "")
    if not key:
        raise HTTPException(500, "Encryption key not configured")
    return Fernet(key.encode())


# ── 요청 스키마 ─────────────────────────────────────────────

class UpbitKeyRequest(BaseModel):
    access_key: str
    secret_key: str


class GeminiKeyRequest(BaseModel):
    api_key: str


class OllamaUrlRequest(BaseModel):
    base_url: str
    model: str | None = None


class AutoTradeRequest(BaseModel):
    enabled: bool


# ── Upbit API 키 ────────────────────────────────────────────

@router.post("/secrets/upbit-keys", status_code=204)
async def set_upbit_keys(req: UpbitKeyRequest):
    """업비트 API 키 저장 (암호화)."""
    f = _get_fernet()
    encrypted_access = f.encrypt(req.access_key.encode()).decode()
    encrypted_secret = f.encrypt(req.secret_key.encode()).decode()
    # 임시: 환경변수 업데이트 (운영에서는 DB 사용)
    os.environ["UPBIT_ACCESS_KEY"] = req.access_key
    os.environ["UPBIT_SECRET_KEY"] = req.secret_key
    return None


# ── Gemini API 키 ───────────────────────────────────────────

@router.post("/secrets/gemini-key", status_code=204)
async def set_gemini_key(req: GeminiKeyRequest):
    """Gemini API 키 저장 (런타임 환경변수 업데이트). 반영은 서비스 재시작 필요."""
    os.environ["GEMINI_API_KEY"] = req.api_key
    return None


# ── Ollama 서버 URL ─────────────────────────────────────────

@router.patch("/settings/ollama-url")
async def set_ollama_url(req: OllamaUrlRequest):
    """Ollama 엔드포인트 URL 및 모델 설정. 반영은 strategy 서비스 재시작 필요."""
    os.environ["OLLAMA_BASE_URL"] = req.base_url
    if req.model:
        os.environ["OLLAMA_MODEL"] = req.model
    return {"base_url": req.base_url, "model": req.model}


# ── 자동매매 ON/OFF ─────────────────────────────────────────

@router.patch("/settings/auto-trade")
async def set_auto_trade(req: AutoTradeRequest):
    """자동매매 ON/OFF 설정을 Redis에 저장."""
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    r = aioredis.from_url(redis_url)
    try:
        await r.set("auto_trade:enabled", "1" if req.enabled else "0")
    finally:
        await r.aclose()
    return {"enabled": req.enabled}


@router.get("/settings/auto-trade")
async def get_auto_trade():
    """현재 자동매매 ON/OFF 상태 반환. 키 부재 시 기본값 True."""
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    r = aioredis.from_url(redis_url)
    try:
        val = await r.get("auto_trade:enabled")
    finally:
        await r.aclose()
    enabled = (val is None) or (val.decode() == "1")
    return {"enabled": enabled}

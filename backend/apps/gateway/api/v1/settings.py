from __future__ import annotations
"""API 키 설정 관리 - 암호화 저장"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from cryptography.fernet import Fernet
import os

router = APIRouter()


def _get_fernet() -> Fernet:
    key = os.environ.get("ENCRYPTION_KEY", "")
    if not key:
        raise HTTPException(500, "Encryption key not configured")
    return Fernet(key.encode())


class UpbitKeyRequest(BaseModel):
    access_key: str
    secret_key: str


class ClaudeKeyRequest(BaseModel):
    api_key: str


@router.post("/secrets/upbit-keys", status_code=204)
async def set_upbit_keys(req: UpbitKeyRequest):
    """업비트 API 키 저장 (암호화)."""
    f = _get_fernet()
    # TODO: DB에 암호화하여 저장
    encrypted_access = f.encrypt(req.access_key.encode()).decode()
    encrypted_secret = f.encrypt(req.secret_key.encode()).decode()
    # 임시: 환경변수 업데이트 (운영에서는 DB 사용)
    os.environ["UPBIT_ACCESS_KEY"] = req.access_key
    os.environ["UPBIT_SECRET_KEY"] = req.secret_key
    return None


@router.post("/secrets/claude-key", status_code=204)
async def set_claude_key(req: ClaudeKeyRequest):
    """Claude API 키 저장."""
    os.environ["CLAUDE_API_KEY"] = req.api_key
    return None

"""Gateway 인증 모듈 - JWT Bearer 토큰 발급 및 검증.

로컬 개발 환경(app_env=local)에서는 인증을 우회합니다.
스테이징/프로덕션에서는 반드시 유효한 JWT 토큰이 필요합니다.

사용법:
  1. POST /api/v1/auth/token  {password: <ADMIN_PASSWORD>} → {access_token, token_type}
  2. 보호된 엔드포인트 호출 시 헤더: Authorization: Bearer <access_token>
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from libs.config import get_settings

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)

ADMIN_PASSWORD_ENV = "ADMIN_PASSWORD"


def _get_admin_password() -> str:
    pw = os.environ.get(ADMIN_PASSWORD_ENV, "")
    if not pw:
        # 미설정 시 jwt_secret을 비밀번호로 사용 (단일 사용자 앱)
        return get_settings().jwt_secret
    return pw


def _create_access_token() -> str:
    settings = get_settings()
    expire = datetime.now(tz=timezone.utc) + timedelta(minutes=settings.jwt_expire_min)
    payload = {"sub": "admin", "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def _verify_token(token: str) -> bool:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
        return payload.get("sub") == "admin"
    except JWTError:
        return False


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """보호된 엔드포인트에 적용하는 FastAPI 의존성.

    - app_env=local: 인증 우회 (개발 편의)
    - 그 외: 유효한 Bearer JWT 필수
    """
    settings = get_settings()
    if settings.app_env == "local":
        return  # 로컬 개발 환경에서는 인증 생략

    if credentials is None or not _verify_token(credentials.credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않거나 만료된 토큰입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── 로그인 엔드포인트 ────────────────────────────────────────

class LoginRequest(BaseModel):
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


@router.post("/auth/token", response_model=TokenResponse, tags=["auth"])
async def login(req: LoginRequest):
    """관리자 비밀번호로 JWT 액세스 토큰 발급.

    비밀번호는 환경변수 ADMIN_PASSWORD (미설정 시 JWT_SECRET 사용).
    """
    if req.password != _get_admin_password():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="비밀번호가 올바르지 않습니다.",
        )
    token = _create_access_token()
    settings = get_settings()
    return TokenResponse(
        access_token=token,
        expires_in_minutes=settings.jwt_expire_min,
    )

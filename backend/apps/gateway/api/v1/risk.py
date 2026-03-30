"""위험 관리 API - Risk service에서 제공하는 지표 조회"""

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException

from apps.gateway.auth import require_auth
from libs.config import get_settings

router = APIRouter()

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
RISK_METRICS_KEY = "risk:metrics"
RISK_STATUS_KEY = "risk:status"
DAILY_PNL_KEY_PREFIX = "risk:daily_pnl:"
RISK_LOSS_STREAK_KEY = "risk:loss_streak"


def _get_redis():
    return aioredis.from_url(REDIS_URL)


def _risk_metric_date(now: datetime | None = None) -> str:
    kst = ZoneInfo("Asia/Seoul")
    ts = now.astimezone(kst) if now else datetime.now(tz=kst)
    return ts.strftime("%Y%m%d")


@router.get("/risk/metrics")
async def get_risk_metrics():
    """현재 위험 지표 조회 (risk_service가 발행한 값)."""
    r = _get_redis()
    try:
        metrics_raw = await r.get(RISK_METRICS_KEY)
        status_raw = await r.get(RISK_STATUS_KEY)

        if metrics_raw is None:
            return {
                "status": "unavailable",
                "message": "Risk service not running or not yet initialized",
            }

        metrics = json.loads(metrics_raw.decode())
        status = status_raw.decode() if status_raw else "unknown"

        return {
            "status": status,
            "dailyPnl": metrics.get("daily_pnl", 0.0),
            "consecutive_losses": metrics.get("consecutive_losses", 0),
            "open_positions": metrics.get("open_positions", 0),
            "total_equity": metrics.get("total_equity", 0.0),
            "available_krw": metrics.get("available_krw", 0.0),
            "daily_loss_pct": (
                abs(metrics.get("daily_pnl", 0.0))
                / max(metrics.get("total_equity", 1), 1)
            ),
            "ts": metrics.get("ts", ""),
        }
    finally:
        await r.aclose()


@router.get("/risk/status")
async def get_risk_status():
    """위험 서비스 상태 조회 (healthy/warning/critical)."""
    r = _get_redis()
    try:
        status_raw = await r.get(RISK_STATUS_KEY)
        if status_raw is None:
            return {"status": "unavailable", "message": "Risk service not running"}

        status = status_raw.decode()
        settings = get_settings()

        daily_pnl_raw = await r.get(f"{DAILY_PNL_KEY_PREFIX}{_risk_metric_date()}")
        daily_pnl = float(daily_pnl_raw.decode()) if daily_pnl_raw else 0.0

        streak_raw = await r.get(RISK_LOSS_STREAK_KEY)
        streak = int(streak_raw.decode()) if streak_raw else 0

        return {
            "status": status,
            "daily_pnl": daily_pnl,
            "consecutive_losses": streak,
            "thresholds": {
                "daily_loss_limit": settings.risk_max_daily_loss_pct,
                "max_position_pct": settings.risk_max_position_pct,
                "max_single_trade_pct": settings.risk_max_single_trade_pct,
                "default_stop_loss_pct": settings.risk_default_stop_loss_pct,
                "default_take_profit_pct": settings.risk_default_take_profit_pct,
            },
        }
    finally:
        await r.aclose()


@router.post("/risk/reset-daily-pnl", dependencies=[Depends(require_auth)])
async def reset_daily_pnl():
    """일일 손익을 0으로 초기화 (새 거래일 시작 시 사용)."""
    r = _get_redis()
    try:
        daily_key = f"{DAILY_PNL_KEY_PREFIX}{_risk_metric_date()}"
        await r.set(daily_key, "0")
        await r.expire(daily_key, 60 * 60 * 48)
        return {"daily_pnl": 0.0, "date": _risk_metric_date()}
    finally:
        await r.aclose()

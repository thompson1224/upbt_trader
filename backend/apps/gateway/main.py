from __future__ import annotations
"""FastAPI Gateway - REST API + WebSocket 진입점"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.gateway.api.v1 import (
    audit,
    backtests,
    manual_orders,
    markets,
    orders,
    portfolio,
    settings as settings_router,
    signals,
)
from apps.gateway.ws import market_ws, signal_ws, order_ws, trade_event_ws
from libs.config import get_settings
from libs.db.session import get_engine
from libs.db.models import Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작: DB 테이블 생성 (Alembic 마이그레이션 사용 전 개발용)
    settings = get_settings()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Redis → WebSocket 브릿지 시작
    import asyncio
    tasks = [
        asyncio.create_task(market_ws.start_redis_subscriber()),
        asyncio.create_task(signal_ws.start_redis_subscriber()),
        asyncio.create_task(trade_event_ws.start_trade_event_subscriber()),
        asyncio.create_task(trade_event_ws.start_portfolio_subscriber()),
    ]

    yield

    # 종료
    for t in tasks:
        t.cancel()
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Upbit AI Trader API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env != "prod" else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # REST 라우터
    prefix = "/api/v1"
    app.include_router(markets.router, prefix=prefix, tags=["markets"])
    app.include_router(signals.router, prefix=prefix, tags=["signals"])
    app.include_router(orders.router, prefix=prefix, tags=["orders"])
    app.include_router(portfolio.router, prefix=prefix, tags=["portfolio"])
    app.include_router(audit.router, prefix=prefix, tags=["audit"])
    app.include_router(backtests.router, prefix=prefix, tags=["backtests"])
    app.include_router(manual_orders.router, prefix=prefix, tags=["manual-orders"])
    app.include_router(settings_router.router, prefix=prefix, tags=["settings"])

    # WebSocket 라우터
    app.include_router(market_ws.router, tags=["websocket"])
    app.include_router(signal_ws.router, tags=["websocket"])
    app.include_router(order_ws.router, tags=["websocket"])
    app.include_router(trade_event_ws.router, tags=["websocket"])

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "service": "gateway"}

    return app


app = create_app()

from __future__ import annotations

"""주문 실행 서비스 - 신호 수신 → 위험 검증 → 주문 전송 → 체결 동기화"""
import asyncio
import logging
import os

import redis.asyncio as aioredis

from libs.config import get_settings
from libs.db.session import get_session_factory
from libs.upbit.rest_client import UpbitRestClient
from apps.risk_service.guards.pre_trade_guard import PreTradeRiskGuard, PositionSizer

from .portfolio import (
    POSITION_SOURCE_STRATEGY,
    POSITION_SOURCE_EXTERNAL,
    POSITION_SOURCE_OVERRIDE_KEY_PREFIX,
    EXTERNAL_POSITION_SL_REDIS_KEY,
    PortfolioManager,
)
from .fill_processor import FillProcessor
from .order_flow import (
    MANUAL_TEST_STRATEGY_ID,
    MANUAL_TEST_MODE_REDIS_KEY,
    MIN_BUY_FINAL_SCORE_REDIS_KEY,
    BLOCKED_BUY_HOUR_BLOCKS_REDIS_KEY,
    OrderFlow,
)
from .position_guard import PositionGuard

# Re-export constants used by other modules (gateway settings, tests, etc.)
__all__ = [
    "MANUAL_TEST_STRATEGY_ID",
    "MANUAL_TEST_MODE_REDIS_KEY",
    "POSITION_SOURCE_STRATEGY",
    "POSITION_SOURCE_EXTERNAL",
    "POSITION_SOURCE_OVERRIDE_KEY_PREFIX",
    "EXTERNAL_POSITION_SL_REDIS_KEY",
]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 5
ORDER_SYNC_INTERVAL_SEC = 10
SL_TP_INTERVAL_SEC = 10
BALANCE_SYNC_INTERVAL_SEC = 30


class ExecutionService:
    def __init__(self):
        self.settings = get_settings()
        self.upbit = UpbitRestClient()
        self.risk_guard = PreTradeRiskGuard()
        self.sizer = PositionSizer()
        self.session_factory = get_session_factory()
        self._kill_switch = False
        redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        self._redis = aioredis.from_url(redis_url)

        self._fill_processor = FillProcessor(
            session_factory=self.session_factory,
            upbit=self.upbit,
            redis=self._redis,
            settings=self.settings,
        )
        self._portfolio = PortfolioManager(
            session_factory=self.session_factory,
            upbit=self.upbit,
            redis=self._redis,
            settings=self.settings,
            compute_risk_metrics=self._fill_processor._compute_risk_metrics,
        )
        self._order_flow = OrderFlow(
            session_factory=self.session_factory,
            upbit=self.upbit,
            redis=self._redis,
            settings=self.settings,
            risk_guard=self.risk_guard,
            sizer=self.sizer,
            compute_risk_metrics=self._fill_processor._compute_risk_metrics,
            update_signal_status=self._update_signal_status,
        )
        self._position_guard = PositionGuard(
            session_factory=self.session_factory,
            upbit=self.upbit,
            redis=self._redis,
            settings=self.settings,
        )

    async def run(self):
        logger.info("Execution service started.")
        await self._fill_processor._restore_runtime_state_from_db()
        await self._order_flow._recover_orphaned_claimed_signals()
        daily_pnl, loss_streak = await self._fill_processor._compute_risk_metrics()
        await self._fill_processor._persist_risk_metrics_to_db(daily_pnl, loss_streak)
        try:
            await self._portfolio._sync_exchange_positions_once()
        except Exception as e:
            logger.warning("Initial exchange position sync failed: %s", e)

        await asyncio.gather(
            self._signal_poll_loop(),
            self._order_sync_loop(),
            self._sl_tp_monitor_loop(),
            self._balance_sync_loop(),
        )

    # ── 루프 ──────────────────────────────────────────────────

    async def _signal_poll_loop(self):
        while not self._kill_switch:
            try:
                await self._order_flow._process_new_signals()
            except Exception as e:
                logger.error("Signal poll error: %s", e)
            await asyncio.sleep(POLL_INTERVAL_SEC)

    async def _order_sync_loop(self):
        while not self._kill_switch:
            try:
                changed = await self._fill_processor._sync_pending_orders()
                if changed:
                    await self._portfolio._store_portfolio_snapshot([])
            except Exception as e:
                logger.error("Order sync error: %s", e)
            await asyncio.sleep(ORDER_SYNC_INTERVAL_SEC)

    async def _sl_tp_monitor_loop(self):
        while not self._kill_switch:
            try:
                portfolio_rows = await self._position_guard._check_all_positions_sl_tp()
                await self._portfolio._store_portfolio_snapshot(portfolio_rows)
            except Exception as e:
                logger.error("SL/TP monitor error: %s", e)
            await asyncio.sleep(SL_TP_INTERVAL_SEC)

    async def _balance_sync_loop(self):
        while not self._kill_switch:
            try:
                await self._portfolio._sync_exchange_positions_once()
            except Exception as e:
                logger.warning("Exchange position sync failed: %s", e)
            await asyncio.sleep(BALANCE_SYNC_INTERVAL_SEC)

    # ── 공통 헬퍼 (다른 서브모듈이 참조하는 정적 메서드) ────────

    @staticmethod
    async def _update_signal_status(db, signal, status: str, reason: str | None):
        from libs.db.models import Signal as SignalModel
        db_signal = await db.get(SignalModel, signal.id)
        if db_signal:
            db_signal.status = status
            if reason:
                db_signal.rejection_reason = reason[:200]
            await db.commit()


async def main():
    service = ExecutionService()
    await service.run()


if __name__ == "__main__":
    asyncio.run(main())

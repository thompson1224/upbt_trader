"""주문 흐름 모듈 - 신호 처리, 위험 검증, 주문 제출."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from libs.db.models import Coin, Order, Position, Signal
from apps.risk_service.guards.pre_trade_guard import AccountState

from .portfolio import (
    _extract_exchange_position_rows,
    _extract_total_krw_balance,
    _is_market_warning as _is_market_warning_helper,
    _resolve_protection_levels,
    POSITION_SOURCE_STRATEGY,
)

logger = logging.getLogger(__name__)

# ── 상수 ──────────────────────────────────────────────────────────────────────

MANUAL_TEST_MODE_REDIS_KEY = "settings:manual_test_mode:enabled"
MIN_BUY_FINAL_SCORE_REDIS_KEY = "settings:min_buy_final_score"
BLOCKED_BUY_HOUR_BLOCKS_REDIS_KEY = "settings:blocked_buy_hour_blocks"
MANUAL_TEST_STRATEGY_ID = "manual-test"
ALLOWED_KST_HOUR_BLOCKS = ("00-04", "04-08", "08-12", "12-16", "16-20", "20-24")
RISK_REQUEST_CHANNEL = "upbit:risk:request"
RISK_RESPONSE_CHANNEL = "upbit:risk:response"
RISK_RPC_TIMEOUT_SEC = 5.0
MIN_PROFIT_THRESHOLD = 0.003

_MARKET_WARNING_VALUES = {
    "CAUTION",
    "WARNING",
    "PRICE_FLUCTUATIONS",
    "TRADING_VOLUME_SOARING",
}

# ── 순수 헬퍼 함수 ────────────────────────────────────────────────────────────


def _is_market_warning(raw: str | None) -> bool:
    return raw in _MARKET_WARNING_VALUES


def _is_manual_test_signal(strategy_id: str) -> bool:
    return strategy_id == MANUAL_TEST_STRATEGY_ID


def _can_execute_signal(
    *,
    strategy_id: str,
    auto_trade_enabled: bool,
    manual_test_mode_enabled: bool,
) -> bool:
    return auto_trade_enabled or (
        manual_test_mode_enabled and _is_manual_test_signal(strategy_id)
    )


def _resolve_manual_test_qty(
    *,
    side: str,
    suggested_qty: float | None,
    position_qty: float,
) -> float:
    if side == "buy":
        return suggested_qty or 0.0
    if suggested_qty is not None:
        return min(suggested_qty, position_qty)
    return position_qty


def _is_buy_signal_below_final_score_threshold(
    *,
    side: str,
    final_score: float,
    min_buy_final_score: float,
    manual_test_signal: bool,
) -> bool:
    if manual_test_signal or side != "buy":
        return False
    return final_score < max(min_buy_final_score, 0.0)


def _kst_hour_block(ts: datetime | None) -> str:
    kst = ZoneInfo("Asia/Seoul")
    current = ts.astimezone(kst) if ts is not None else datetime.now(tz=kst)
    hour = current.hour
    start = (hour // 4) * 4
    end = start + 4
    return f"{start:02d}-{end:02d}"


def _is_buy_signal_blocked_by_hour_block(
    *,
    side: str,
    signal_ts: datetime | None,
    blocked_blocks: set[str],
    manual_test_signal: bool,
) -> bool:
    if manual_test_signal or side != "buy" or not blocked_blocks:
        return False
    return _kst_hour_block(signal_ts) in blocked_blocks


def _resolve_market_buy_krw_amount(
    *,
    requested_qty: float,
    entry_price: float,
    available_krw: float,
    min_order_krw: float,
    fee_rate: float = 0.0005,
) -> int:
    """시장가 매수 총액을 가용 KRW 상한으로 보정."""
    requested_krw = int(round(requested_qty * entry_price))
    if requested_krw <= 0 or entry_price <= 0 or available_krw <= 0:
        return 0
    max_affordable_krw = int(available_krw / (1 + max(fee_rate, 0.0)))
    safe_krw = min(requested_krw, max_affordable_krw)
    if safe_krw < min_order_krw:
        return 0
    return safe_krw


def _should_enforce_expected_profit_threshold(
    side: str,
    manual_test_signal: bool,
) -> bool:
    return side == "buy" and not manual_test_signal


# ── OrderFlow 클래스 ──────────────────────────────────────────────────────────


class OrderFlow:
    def __init__(
        self,
        *,
        session_factory,
        upbit,
        redis,
        settings,
        risk_guard,
        sizer,
        compute_risk_metrics,
        update_signal_status,
    ):
        self.session_factory = session_factory
        self.upbit = upbit
        self.redis = redis
        self.settings = settings
        self.risk_guard = risk_guard
        self.sizer = sizer
        self._compute_risk_metrics = compute_risk_metrics
        self._update_signal_status = update_signal_status

    async def _is_auto_trade_enabled(self) -> bool:
        try:
            val = await self.redis.get("auto_trade:enabled")
            if val is None:
                logger.warning("auto_trade flag missing in Redis; fail-closed to disabled")
                return False
            return val.decode() == "1"
        except Exception as e:
            logger.warning("Failed to read auto_trade flag from Redis: %s", e)
            return False

    async def _is_manual_test_mode_enabled(self) -> bool:
        try:
            val = await self.redis.get(MANUAL_TEST_MODE_REDIS_KEY)
            return val is not None and val.decode() == "1"
        except Exception as e:
            logger.warning("Failed to read manual test mode flag from Redis: %s", e)
            return False

    async def _get_min_buy_final_score(self) -> float:
        try:
            val = await self.redis.get(MIN_BUY_FINAL_SCORE_REDIS_KEY)
            if val is None:
                return 0.0
            return max(float(val.decode()), 0.0)
        except Exception as e:
            logger.warning("Failed to read min buy final score from Redis: %s", e)
            return 0.0

    async def _get_blocked_buy_hour_blocks(self) -> set[str]:
        try:
            val = await self.redis.get(BLOCKED_BUY_HOUR_BLOCKS_REDIS_KEY)
            if val is None:
                return set()
            payload = json.loads(val.decode())
            if not isinstance(payload, list):
                return set()
            return {
                str(item).strip()
                for item in payload
                if str(item).strip() in ALLOWED_KST_HOUR_BLOCKS
            }
        except Exception as e:
            logger.warning("Failed to read blocked buy hour blocks from Redis: %s", e)
            return set()

    async def _evaluate_risk_via_rpc(
        self,
        side: str,
        market: str,
        suggested_qty: float,
        entry_price: float,
        stop_loss: float | None,
        account: AccountState,
    ) -> tuple[bool, str, float | None]:
        """risk_service에 RPC로 위험 평가 요청. 실패 시 로컬 평가로 폴백."""
        request_id = str(uuid.uuid4())
        request = {
            "request_id": request_id,
            "side": side,
            "market": market,
            "suggested_qty": suggested_qty,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "account": {
                "total_equity": account.total_equity,
                "available_krw": account.available_krw,
                "daily_pnl": account.daily_pnl,
                "consecutive_losses": account.consecutive_losses,
                "open_positions_count": account.open_positions_count,
                "market_warning": account.market_warning,
            },
        }

        try:
            pubsub = self.redis.pubsub()
            await pubsub.subscribe(RISK_RESPONSE_CHANNEL)
            try:
                await self.redis.publish(RISK_REQUEST_CHANNEL, json.dumps(request))

                start_time = asyncio.get_event_loop().time()
                while (
                    asyncio.get_event_loop().time() - start_time
                ) < RISK_RPC_TIMEOUT_SEC:
                    message = await asyncio.wait_for(
                        pubsub.get_message(timeout=0.5), timeout=1.0
                    )
                    if message is None:
                        continue
                    if message["type"] != "message":
                        continue
                    try:
                        response = json.loads(message["data"])
                        if response.get("request_id") == request_id:
                            return (
                                response.get("approved", False),
                                response.get("reason", "Unknown"),
                                response.get("adjusted_qty"),
                            )
                    except json.JSONDecodeError:
                        continue
            finally:
                await pubsub.unsubscribe(RISK_RESPONSE_CHANNEL)
                await pubsub.close()
        except Exception as e:
            logger.warning("Risk RPC failed, using local evaluation: %s", e)

        decision = self.risk_guard.evaluate(
            side=side,
            market=market,
            suggested_qty=suggested_qty,
            entry_price=entry_price,
            stop_loss=stop_loss,
            account=account,
        )
        return (decision.approved, decision.reason, decision.adjusted_qty)

    async def _process_new_signals(self):
        auto_trade_enabled = await self._is_auto_trade_enabled()
        manual_test_mode_enabled = await self._is_manual_test_mode_enabled()

        if not auto_trade_enabled and not manual_test_mode_enabled:
            return

        async with self.session_factory() as db:
            stmt = (
                select(Signal)
                .where(Signal.status == "new")
                .where(Signal.side.in_(["buy", "sell"]))
                .order_by(Signal.ts.asc())
                .limit(10)
            )
            if auto_trade_enabled and not manual_test_mode_enabled:
                stmt = stmt.where(Signal.strategy_id != MANUAL_TEST_STRATEGY_ID)
            elif manual_test_mode_enabled and not auto_trade_enabled:
                stmt = stmt.where(Signal.strategy_id == MANUAL_TEST_STRATEGY_ID)
            result = await db.execute(stmt)
            signals = result.scalars().all()

        for signal in signals:
            await self._execute_signal(signal)

    async def _claim_signal_for_execution(self, signal_id: int) -> bool:
        async with self.session_factory() as db:
            result = await db.execute(
                update(Signal)
                .where(Signal.id == signal_id)
                .where(Signal.status == "new")
                .values(status="approved", rejection_reason=None)
            )
            await db.commit()
            return (result.rowcount or 0) > 0

    async def _recover_orphaned_claimed_signals(self) -> None:
        async with self.session_factory() as db:
            result = await db.execute(select(Signal).where(Signal.status == "approved"))
            approved_signals = result.scalars().all()

            recovered_new = 0
            recovered_executed = 0
            for signal in approved_signals:
                existing_order_id = await self._get_existing_order_id(db, signal.id)
                if existing_order_id is not None:
                    signal.status = "executed"
                    recovered_executed += 1
                    continue
                signal.status = "new"
                recovered_new += 1

            if recovered_new > 0 or recovered_executed > 0:
                await db.commit()
                logger.warning(
                    "Recovered claimed signals: %s back to new, %s marked executed from existing orders",
                    recovered_new,
                    recovered_executed,
                )

    async def _get_existing_order_id(self, db, signal_id: int) -> int | None:
        result = await db.execute(
            select(Order.id).where(Order.signal_id == signal_id).limit(1)
        )
        return result.scalar_one_or_none()

    async def _execute_signal(self, signal: Signal):  # noqa: C901 (복잡도 허용)
        auto_trade_enabled = await self._is_auto_trade_enabled()
        manual_test_mode_enabled = await self._is_manual_test_mode_enabled()
        min_buy_final_score = await self._get_min_buy_final_score()
        blocked_buy_hour_blocks = await self._get_blocked_buy_hour_blocks()
        manual_test_signal = _is_manual_test_signal(signal.strategy_id)

        if not _can_execute_signal(
            strategy_id=signal.strategy_id,
            auto_trade_enabled=auto_trade_enabled,
            manual_test_mode_enabled=manual_test_mode_enabled,
        ):
            logger.info(
                "Execution disabled for signal %s: auto_trade=%s manual_test_mode=%s strategy=%s",
                signal.id, auto_trade_enabled, manual_test_mode_enabled, signal.strategy_id,
            )
            return

        claimed = await self._claim_signal_for_execution(signal.id)
        if not claimed:
            logger.info("Signal %s already claimed or processed by another worker", signal.id)
            return

        async with self.session_factory() as db:
            existing_order_id = await self._get_existing_order_id(db, signal.id)
            if existing_order_id is not None:
                await self._update_signal_status(db, signal, "executed", "Existing order already recorded")
                logger.warning("Signal %s already has order %s; skipping duplicate execution", signal.id, existing_order_id)
                return

        if _is_buy_signal_below_final_score_threshold(
            side=signal.side,
            final_score=signal.final_score,
            min_buy_final_score=min_buy_final_score,
            manual_test_signal=manual_test_signal,
        ):
            async with self.session_factory() as db:
                await self._update_signal_status(
                    db, signal, "rejected",
                    f"Final score {signal.final_score:.2f} < minimum {min_buy_final_score:.2f}",
                )
            return

        if _is_buy_signal_blocked_by_hour_block(
            side=signal.side,
            signal_ts=signal.ts,
            blocked_blocks=blocked_buy_hour_blocks,
            manual_test_signal=manual_test_signal,
        ):
            blocked_hour_block = _kst_hour_block(signal.ts)
            async with self.session_factory() as db:
                await self._update_signal_status(
                    db, signal, "rejected", f"Blocked buy hour block {blocked_hour_block} KST"
                )
            return

        expected_profit = abs(signal.final_score) * 0.02
        if (
            _should_enforce_expected_profit_threshold(signal.side, manual_test_signal)
            and expected_profit < MIN_PROFIT_THRESHOLD
        ):
            async with self.session_factory() as db:
                await self._update_signal_status(
                    db, signal, "rejected",
                    f"Expected profit {expected_profit:.3%} < threshold {MIN_PROFIT_THRESHOLD:.3%}",
                )
            return

        async with self.session_factory() as db:
            coin = await db.get(Coin, signal.coin_id)
            if not coin:
                return

            existing_order_id = await self._get_existing_order_id(db, signal.id)
            if existing_order_id is not None:
                await self._update_signal_status(db, signal, "executed", "Existing order already recorded")
                logger.warning("Signal %s already has order %s inside execution transaction; skipping", signal.id, existing_order_id)
                return

            pos_result = await db.execute(
                select(Position).where(Position.coin_id == signal.coin_id)
            )
            position = pos_result.scalar_one_or_none()

            if signal.side == "buy" and position and position.qty > 0:
                await self._update_signal_status(db, signal, "rejected", "Already in position")
                return

            if signal.side == "sell" and (not position or position.qty <= 0):
                await self._update_signal_status(db, signal, "rejected", "No position to sell")
                return

            current_position_qty = position.qty if position else 0.0

        try:
            balances = await self.upbit.get_balances()
        except Exception as e:
            logger.error("Balance fetch failed: %s", e)
            return

        available_krw, exchange_positions = _extract_exchange_position_rows(balances)
        total_krw = _extract_total_krw_balance(balances)
        total_equity = total_krw + sum(
            payload["qty"] * payload["avg_entry_price"]
            for payload in exchange_positions.values()
        )

        try:
            entry_price = await self.upbit.get_ticker(coin.market)
        except Exception as e:
            async with self.session_factory() as db:
                await self._update_signal_status(db, signal, "rejected", f"Ticker fetch error: {e}")
            logger.error("Ticker fetch failed for %s: %s", coin.market, e)
            return

        if not entry_price or entry_price <= 0:
            async with self.session_factory() as db:
                await self._update_signal_status(db, signal, "rejected", "Invalid ticker price")
            logger.warning("Invalid ticker price for %s, skipping", coin.market)
            return

        daily_pnl, consecutive_losses = await self._compute_risk_metrics()

        async with self.session_factory() as db:
            pos_count_result = await db.execute(select(Position).where(Position.qty > 0))
            open_positions = len(pos_count_result.scalars().all())

        account = AccountState(
            total_equity=total_equity,
            available_krw=available_krw,
            daily_pnl=daily_pnl,
            consecutive_losses=consecutive_losses,
            open_positions_count=open_positions,
            market_warning=_is_market_warning(coin.market_warning),
        )

        if manual_test_signal:
            qty = _resolve_manual_test_qty(
                side=signal.side,
                suggested_qty=signal.suggested_qty,
                position_qty=current_position_qty,
            )
            if qty <= 0:
                async with self.session_factory() as db:
                    await self._update_signal_status(db, signal, "rejected", "Invalid manual test qty")
                return
            order_value = qty * entry_price
            if signal.side == "buy":
                if order_value < self.sizer.MIN_ORDER_KRW:
                    async with self.session_factory() as db:
                        await self._update_signal_status(
                            db, signal, "rejected",
                            f"Manual test order below minimum {self.sizer.MIN_ORDER_KRW} KRW",
                        )
                    return
                if order_value > available_krw:
                    async with self.session_factory() as db:
                        await self._update_signal_status(db, signal, "rejected", "Insufficient KRW")
                    return
            elif order_value < self.sizer.MIN_ORDER_KRW:
                async with self.session_factory() as db:
                    await self._update_signal_status(
                        db, signal, "rejected",
                        f"Manual test sell below minimum {self.sizer.MIN_ORDER_KRW} KRW",
                    )
                return
            if _is_market_warning(coin.market_warning):
                async with self.session_factory() as db:
                    await self._update_signal_status(
                        db, signal, "rejected", f"Market warning active for {coin.market}"
                    )
                return
        elif signal.side == "buy":
            stop_loss, _take_profit = _resolve_protection_levels(
                entry_price,
                signal.suggested_stop_loss,
                signal.suggested_take_profit,
                self.settings.risk_default_stop_loss_pct,
                self.settings.risk_default_take_profit_pct,
            )
            if stop_loss is None:
                stop_loss = entry_price * 0.97
            qty = self.sizer.calculate_qty(
                equity=total_equity,
                entry_price=entry_price,
                stop_loss=stop_loss,
            )
            if qty <= 0:
                if available_krw >= self.sizer.MIN_ORDER_KRW:
                    qty = self.sizer.MIN_ORDER_KRW / entry_price
                else:
                    async with self.session_factory() as db:
                        await self._update_signal_status(db, signal, "rejected", "Insufficient qty")
                    return
        else:
            async with self.session_factory() as db:
                pos_result = await db.execute(
                    select(Position).where(Position.coin_id == signal.coin_id)
                )
                position = pos_result.scalar_one_or_none()
                qty = position.qty if position else 0

        if manual_test_signal:
            final_qty = qty
        else:
            approved, reason, adjusted_qty = await self._evaluate_risk_via_rpc(
                side=signal.side,
                market=coin.market,
                suggested_qty=qty,
                entry_price=entry_price,
                stop_loss=signal.suggested_stop_loss,
                account=account,
            )

            if not approved:
                async with self.session_factory() as db:
                    await self._update_signal_status(db, signal, "rejected", reason)
                logger.warning("Signal rejected: %s - %s", signal.id, reason)
                try:
                    await self.redis.publish(
                        "upbit:trade_event",
                        json.dumps({"type": "risk_rejected", "market": coin.market, "reason": reason}),
                    )
                except Exception:
                    pass
                return

            final_qty = adjusted_qty if adjusted_qty is not None else qty

        try:
            if signal.side == "buy":
                krw_amount = _resolve_market_buy_krw_amount(
                    requested_qty=final_qty,
                    entry_price=entry_price,
                    available_krw=available_krw,
                    min_order_krw=self.sizer.MIN_ORDER_KRW,
                )
                if krw_amount < self.sizer.MIN_ORDER_KRW:
                    async with self.session_factory() as db:
                        await self._update_signal_status(db, signal, "rejected", "Insufficient KRW after fee buffer")
                    return
                order_volume = krw_amount / entry_price
                result = await self.upbit.place_order(
                    market=coin.market, side="bid", volume=None, price=krw_amount, ord_type="price",
                )
            else:
                order_volume = final_qty
                result = await self.upbit.place_order(
                    market=coin.market, side="ask", volume=final_qty, price=None, ord_type="market",
                )

            async with self.session_factory() as db:
                try:
                    order = Order(
                        signal_id=signal.id,
                        coin_id=signal.coin_id,
                        exchange_order_id=result.get("uuid"),
                        side="bid" if signal.side == "buy" else "ask",
                        ord_type="price" if signal.side == "buy" else "market",
                        price=entry_price,
                        volume=order_volume,
                        state=result.get("state", "wait"),
                        requested_at=datetime.now(tz=timezone.utc),
                    )
                    db.add(order)
                    db_signal = await db.get(Signal, signal.id)
                    if db_signal:
                        db_signal.status = "executed"
                        db_signal.rejection_reason = None
                    await db.commit()
                except IntegrityError:
                    await db.rollback()
                    existing_order_id = await self._get_existing_order_id(db, signal.id)
                    if existing_order_id is not None:
                        await self._update_signal_status(db, signal, "executed", "Existing order already recorded")
                        logger.warning(
                            "Duplicate order insert blocked for signal %s; existing order %s reused",
                            signal.id, existing_order_id,
                        )
                        return
                    raise

            logger.info("Order placed: %s %s qty=%.6f uuid=%s", coin.market, signal.side, order_volume, result.get("uuid"))

            try:
                await self.redis.publish(
                    "upbit:trade_event",
                    json.dumps({
                        "type": "order_placed",
                        "market": coin.market,
                        "side": "bid" if signal.side == "buy" else "ask",
                        "price": entry_price,
                        "volume": order_volume,
                    }),
                )
            except Exception:
                pass

        except Exception as e:
            async with self.session_factory() as db:
                await self._update_signal_status(db, signal, "rejected", str(e))
            try:
                await self.redis.publish(
                    "upbit:trade_event",
                    json.dumps({
                        "type": "order_failed",
                        "market": coin.market,
                        "side": "bid" if signal.side == "buy" else "ask",
                        "reason": str(e),
                        "signalId": signal.id,
                    }),
                )
            except Exception:
                pass
            logger.error("Order failed: %s - %s", coin.market, e)

from __future__ import annotations
"""주문 실행 서비스 - 신호 수신 → 위험 검증 → 주문 전송 → 체결 동기화"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis
from sqlalchemy import select

from libs.config import get_settings
from libs.db.session import get_session_factory
from libs.db.models import Signal, Order, Fill, Position, Coin
from libs.upbit.rest_client import UpbitRestClient
from apps.risk_service.guards.pre_trade_guard import (
    PreTradeRiskGuard, PositionSizer, AccountState,
)

# Upbit 시장 경보 값 (이 값만 True 처리)
_MARKET_WARNING_VALUES = {"CAUTION", "WARNING", "PRICE_FLUCTUATIONS", "TRADING_VOLUME_SOARING"}


def _is_market_warning(raw: str | None) -> bool:
    """Upbit market_warning 문자열 → bool. "NONE"과 None은 False."""
    return raw in _MARKET_WARNING_VALUES


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 5         # 신호 폴링 주기
ORDER_SYNC_INTERVAL_SEC = 10  # 미체결 주문 동기화 주기
SL_TP_INTERVAL_SEC = 10       # SL/TP 모니터 주기


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

    async def run(self):
        logger.info("Execution service started.")
        await asyncio.gather(
            self._signal_poll_loop(),
            self._order_sync_loop(),
            self._sl_tp_monitor_loop(),
        )

    # ── 자동매매 ON/OFF 플래그 ──────────────────────────────

    async def _is_auto_trade_enabled(self) -> bool:
        """Redis의 auto_trade:enabled 키를 읽어 ON/OFF 반환.
        키 부재 또는 Redis 장애 시 True (기존 동작 유지).
        """
        try:
            val = await self._redis.get("auto_trade:enabled")
            if val is None:
                return True  # 키 없음 = 기본값 활성화
            return val.decode() == "1"
        except Exception as e:
            logger.warning("Failed to read auto_trade flag from Redis: %s", e)
            return True  # Redis 장애 시 폴백: 거래 허용

    # ── 신호 폴링 루프 ──────────────────────────────────────

    async def _signal_poll_loop(self):
        """새 신호를 주기적으로 폴링하여 주문 실행."""
        while not self._kill_switch:
            try:
                await self._process_new_signals()
            except Exception as e:
                logger.error("Signal poll error: %s", e)
            await asyncio.sleep(POLL_INTERVAL_SEC)

    async def _compute_risk_metrics(self) -> tuple[float, int]:
        """
        오늘 실현손익(daily_pnl)과 연속 손실 횟수를 fills로부터 계산.
        - daily_pnl : KST 오늘 0시 이후 매도 체결의 손익 합계
        - consecutive_losses : 최근 매도 체결 20건 중 연속 손실 횟수
        단일 세션으로 배치 조회해 N+1 문제 방지.
        """
        kst = ZoneInfo("Asia/Seoul")
        today_start_kst = datetime.now(tz=kst).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).astimezone(timezone.utc)

        async with self.session_factory() as db:
            fills_result = await db.execute(
                select(Fill, Order, Position)
                .join(Order, Fill.order_id == Order.id)
                .join(Position, Position.coin_id == Order.coin_id, isouter=True)
                .where(Order.side == "ask")
                .where(Fill.filled_at >= today_start_kst)
                .order_by(Fill.filled_at.asc())
            )
            today_rows = fills_result.all()

            recent_result = await db.execute(
                select(Fill, Order, Position)
                .join(Order, Fill.order_id == Order.id)
                .join(Position, Position.coin_id == Order.coin_id, isouter=True)
                .where(Order.side == "ask")
                .order_by(Fill.filled_at.desc())
                .limit(20)
            )
            recent_rows = recent_result.all()

        daily_pnl = 0.0
        for fill, order, pos in today_rows:
            if pos and pos.avg_entry_price > 0:
                daily_pnl += (fill.price - pos.avg_entry_price) * fill.volume - fill.fee

        loss_streak = 0
        for fill, order, pos in recent_rows:
            if pos and pos.avg_entry_price > 0:
                trade_pnl = (fill.price - pos.avg_entry_price) * fill.volume - fill.fee
                if trade_pnl < 0:
                    loss_streak += 1
                else:
                    break
            else:
                break

        return daily_pnl, loss_streak

    async def _process_new_signals(self):
        async with self.session_factory() as db:
            result = await db.execute(
                select(Signal)
                .where(Signal.status == "new")
                .where(Signal.side.in_(["buy", "sell"]))
                .order_by(Signal.ts.asc())
                .limit(10)
            )
            signals = result.scalars().all()

        for signal in signals:
            await self._execute_signal(signal)

    async def _execute_signal(self, signal: Signal):
        # ── 자동매매 스위치 확인 ────────────────────────────
        if not await self._is_auto_trade_enabled():
            logger.info("Auto-trade is OFF. Skipping signal %s", signal.id)
            return  # 상태 "new" 유지 → 재활성화 시 재처리

        async with self.session_factory() as db:
            coin = await db.get(Coin, signal.coin_id)
            if not coin:
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

        try:
            balances = await self.upbit.get_balances()
        except Exception as e:
            logger.error("Balance fetch failed: %s", e)
            return

        krw_balance = next(
            (float(b["balance"]) for b in balances if b["currency"] == "KRW"), 0.0
        )
        total_equity = sum(
            float(b["balance"]) * float(b.get("avg_buy_price", 1))
            for b in balances
            if b["currency"] != "KRW"
        ) + krw_balance

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
            pos_count_result = await db.execute(
                select(Position).where(Position.qty > 0)
            )
            open_positions = len(pos_count_result.scalars().all())

        account = AccountState(
            total_equity=total_equity,
            available_krw=krw_balance,
            daily_pnl=daily_pnl,
            consecutive_losses=consecutive_losses,
            open_positions_count=open_positions,
            market_warning=_is_market_warning(coin.market_warning),
        )

        if signal.side == "buy":
            stop_loss = signal.suggested_stop_loss or (entry_price * 0.97)
            qty = self.sizer.calculate_qty(
                equity=total_equity,
                entry_price=entry_price,
                stop_loss=stop_loss,
            )
            if qty <= 0:
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

        decision = self.risk_guard.evaluate(
            side=signal.side,
            market=coin.market,
            suggested_qty=qty,
            entry_price=entry_price,
            stop_loss=signal.suggested_stop_loss,
            account=account,
        )

        if not decision.approved:
            async with self.session_factory() as db:
                await self._update_signal_status(db, signal, "rejected", decision.reason)
            logger.warning("Signal rejected: %s - %s", signal.id, decision.reason)
            # 거절 이벤트 브로드캐스트
            try:
                await self._redis.publish("upbit:trade_event", json.dumps({
                    "type": "risk_rejected",
                    "market": coin.market,
                    "reason": decision.reason,
                }))
            except Exception:
                pass
            return

        final_qty = decision.adjusted_qty or qty

        try:
            if signal.side == "buy":
                result = await self.upbit.place_order(
                    market=coin.market,
                    side="bid",
                    volume=final_qty,
                    price=None,
                    ord_type="market",
                )
            else:
                result = await self.upbit.place_order(
                    market=coin.market,
                    side="ask",
                    volume=final_qty,
                    price=None,
                    ord_type="market",
                )

            async with self.session_factory() as db:
                order = Order(
                    signal_id=signal.id,
                    coin_id=signal.coin_id,
                    exchange_order_id=result.get("uuid"),
                    side="bid" if signal.side == "buy" else "ask",
                    ord_type="market",
                    volume=final_qty,
                    state=result.get("state", "wait"),
                    requested_at=datetime.now(tz=timezone.utc),
                )
                db.add(order)
                await self._update_signal_status(db, signal, "executed", None)
                # 매수 시 포지션에 SL/TP 설정
                if signal.side == "buy":
                    await self._set_position_sl_tp(
                        db, signal.coin_id,
                        signal.suggested_stop_loss,
                        signal.suggested_take_profit,
                    )
                await db.commit()

            logger.info(
                "Order placed: %s %s qty=%.6f uuid=%s",
                coin.market, signal.side, final_qty, result.get("uuid"),
            )

            # 주문 접수 이벤트 브로드캐스트
            try:
                await self._redis.publish("upbit:trade_event", json.dumps({
                    "type": "order_placed",
                    "market": coin.market,
                    "side": "bid" if signal.side == "buy" else "ask",
                    "price": entry_price,
                    "volume": final_qty,
                }))
            except Exception:
                pass

        except Exception as e:
            async with self.session_factory() as db:
                await self._update_signal_status(db, signal, "rejected", str(e))
            logger.error("Order failed: %s - %s", coin.market, e)

    # ── 주문 동기화 루프 ────────────────────────────────────

    async def _order_sync_loop(self):
        """미체결 주문 상태를 주기적으로 업비트와 동기화."""
        while not self._kill_switch:
            try:
                await self._sync_pending_orders()
            except Exception as e:
                logger.error("Order sync error: %s", e)
            await asyncio.sleep(ORDER_SYNC_INTERVAL_SEC)

    async def _sync_pending_orders(self):
        async with self.session_factory() as db:
            result = await db.execute(
                select(Order).where(Order.state.in_(["wait", "watch"]))
            )
            pending = result.scalars().all()

        for order in pending:
            if not order.exchange_order_id:
                continue
            try:
                info = await self.upbit.get_order(order.exchange_order_id)
                new_state = info.get("state", order.state)

                async with self.session_factory() as db:
                    db_order = await db.get(Order, order.id)
                    if db_order:
                        db_order.state = new_state

                        if new_state == "done":
                            for trade in info.get("trades", []):
                                fill = Fill(
                                    order_id=order.id,
                                    trade_uuid=trade["uuid"],
                                    price=float(trade["price"]),
                                    volume=float(trade["volume"]),
                                    fee=float(trade.get("funds", 0)) * 0.0005,
                                    filled_at=datetime.now(tz=timezone.utc),
                                )
                                db.add(fill)

                            await self._update_position(db, order, info)

                            # 체결 이벤트 브로드캐스트
                            try:
                                executed_funds = float(info.get("executed_funds", 0))
                                executed_volume = float(info.get("executed_volume", 0))
                                avg_price = executed_funds / executed_volume if executed_volume > 0 else 0
                                await self._redis.publish("upbit:trade_event", json.dumps({
                                    "type": "order_filled",
                                    "market": "",  # order에 market 정보 없으면 생략
                                    "side": order.side,
                                    "price": avg_price,
                                    "volume": executed_volume,
                                }))
                            except Exception:
                                pass

                        await db.commit()
            except Exception as e:
                logger.warning("Order sync failed for %s: %s", order.exchange_order_id, e)

    async def _update_position(self, db, order: Order, order_info: dict):
        """체결 완료 후 포지션 업데이트."""
        executed_volume = float(order_info.get("executed_volume", 0))
        executed_funds = float(order_info.get("executed_funds", 0))
        if executed_volume <= 0:
            return

        avg_price = executed_funds / executed_volume

        pos_result = await db.execute(
            select(Position).where(Position.coin_id == order.coin_id)
        )
        position = pos_result.scalar_one_or_none()

        if order.side == "bid":  # 매수
            if position:
                total_qty = position.qty + executed_volume
                position.avg_entry_price = (
                    position.avg_entry_price * position.qty + avg_price * executed_volume
                ) / total_qty
                position.qty = total_qty
            else:
                position = Position(
                    coin_id=order.coin_id,
                    qty=executed_volume,
                    avg_entry_price=avg_price,
                )
                db.add(position)
        elif order.side == "ask" and position:  # 매도
            pnl = (avg_price - position.avg_entry_price) * executed_volume
            position.realized_pnl += pnl
            position.qty = max(0, position.qty - executed_volume)
            if position.qty <= 0:
                position.stop_loss = None
                position.take_profit = None

    async def _set_position_sl_tp(
        self, db, coin_id: int,
        stop_loss: float | None, take_profit: float | None,
    ):
        """매수 주문 후 포지션에 SL/TP 설정."""
        pos_result = await db.execute(
            select(Position).where(Position.coin_id == coin_id)
        )
        position = pos_result.scalar_one_or_none()
        if position:
            if stop_loss is not None:
                position.stop_loss = stop_loss
            if take_profit is not None:
                position.take_profit = take_profit

    # ── SL/TP 모니터 루프 ───────────────────────────────────

    async def _sl_tp_monitor_loop(self):
        """열린 포지션의 SL/TP를 10초마다 확인하고, 조건 충족 시 시장가 매도."""
        while not self._kill_switch:
            try:
                await self._check_all_positions_sl_tp()
            except Exception as e:
                logger.error("SL/TP monitor error: %s", e)
            await asyncio.sleep(SL_TP_INTERVAL_SEC)

    async def _check_all_positions_sl_tp(self):
        async with self.session_factory() as db:
            result = await db.execute(
                select(Position, Coin)
                .join(Coin, Position.coin_id == Coin.id)
                .where(Position.qty > 0)
            )
            rows = result.all()

        for position, coin in rows:
            try:
                await self._check_position_sl_tp(position, coin)
            except Exception as e:
                logger.warning("SL/TP check failed for %s: %s", coin.market, e)

    async def _check_position_sl_tp(self, position: Position, coin: Coin):
        """단일 포지션 SL/TP 확인 + 미실현 손익 갱신."""
        current_price = await self.upbit.get_ticker(coin.market)
        if not current_price or current_price <= 0:
            return

        unrealized_pnl = (current_price - position.avg_entry_price) * position.qty

        sl_triggered = (
            position.stop_loss is not None
            and current_price <= position.stop_loss
        )
        tp_triggered = (
            position.take_profit is not None
            and current_price >= position.take_profit
        )

        trigger_reason: str | None = None
        if sl_triggered:
            trigger_reason = f"SL triggered: {current_price:.0f} <= {position.stop_loss:.0f}"
        elif tp_triggered:
            trigger_reason = f"TP triggered: {current_price:.0f} >= {position.take_profit:.0f}"

        # 미실현 손익 갱신 (항상)
        async with self.session_factory() as db:
            db_pos = await db.get(Position, position.id)
            if not db_pos or db_pos.qty <= 0:
                return  # 이미 청산됨 (레이스 컨디션 방어)
            db_pos.unrealized_pnl = unrealized_pnl
            await db.commit()

        # Redis 브로드캐스트 — 미실현 손익 변경
        try:
            await self._redis.publish("upbit:position_update", json.dumps({
                "coinId": position.coin_id,
                "market": coin.market,
                "qty": position.qty,
                "avgEntryPrice": position.avg_entry_price,
                "currentPrice": current_price,
                "unrealizedPnl": unrealized_pnl,
                "stopLoss": position.stop_loss,
                "takeProfit": position.take_profit,
            }))
        except Exception as e:
            logger.warning("Failed to publish position_update: %s", e)

        # SL/TP 트리거 시 시장가 매도
        if trigger_reason:
            logger.info("Position close triggered for %s: %s", coin.market, trigger_reason)
            await self._execute_sl_tp_sell(position, coin, trigger_reason)

    async def _execute_sl_tp_sell(self, position: Position, coin: Coin, reason: str):
        """
        SL/TP 조건 충족 시 시장가 매도 직접 실행.
        주의: auto_trade 스위치와 무관하게 항상 실행 (손실 방지 목적).
        """
        qty = position.qty
        try:
            result = await self.upbit.place_order(
                market=coin.market,
                side="ask",
                volume=qty,
                price=None,
                ord_type="market",
            )
        except Exception as e:
            logger.error("SL/TP sell failed for %s: %s", coin.market, e)
            return

        async with self.session_factory() as db:
            order = Order(
                signal_id=None,
                coin_id=coin.id,
                exchange_order_id=result.get("uuid"),
                side="ask",
                ord_type="market",
                volume=qty,
                state=result.get("state", "wait"),
                rejected_reason=reason[:200],
                requested_at=datetime.now(tz=timezone.utc),
            )
            db.add(order)
            await db.commit()

        logger.info(
            "SL/TP order placed: %s qty=%.6f uuid=%s reason=%s",
            coin.market, qty, result.get("uuid"), reason,
        )

        # SL/TP 이벤트 브로드캐스트
        try:
            event_type = "sl_triggered" if "SL" in reason else "tp_triggered"
            current_price = await self.upbit.get_ticker(coin.market)
            await self._redis.publish("upbit:trade_event", json.dumps({
                "type": event_type,
                "market": coin.market,
                "price": current_price,
            }))
        except Exception:
            pass

    # ── 공통 헬퍼 ──────────────────────────────────────────

    @staticmethod
    async def _update_signal_status(db, signal: Signal, status: str, reason: str | None):
        db_signal = await db.get(Signal, signal.id)
        if db_signal:
            db_signal.status = status
            if reason:
                db_signal.rejection_reason = reason[:200]


async def main():
    service = ExecutionService()
    await service.run()


if __name__ == "__main__":
    asyncio.run(main())

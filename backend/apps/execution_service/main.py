from __future__ import annotations
"""주문 실행 서비스 - 신호 수신 → 위험 검증 → 주문 전송 → 체결 동기화"""
import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

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

POLL_INTERVAL_SEC = 5      # 신호 폴링 주기
ORDER_SYNC_INTERVAL_SEC = 10  # 미체결 주문 동기화 주기


class ExecutionService:
    def __init__(self):
        self.settings = get_settings()
        self.upbit = UpbitRestClient()
        self.risk_guard = PreTradeRiskGuard()
        self.sizer = PositionSizer()
        self.session_factory = get_session_factory()
        self._kill_switch = False

    async def run(self):
        logger.info("Execution service started.")
        await asyncio.gather(
            self._signal_poll_loop(),
            self._order_sync_loop(),
        )

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
            # 오늘 KST 체결 매도 fill + 연결된 order + coin_id별 position 배치 조회
            fills_result = await db.execute(
                select(Fill, Order, Position)
                .join(Order, Fill.order_id == Order.id)
                .join(Position, Position.coin_id == Order.coin_id, isouter=True)
                .where(Order.side == "ask")
                .where(Fill.filled_at >= today_start_kst)
                .order_by(Fill.filled_at.asc())
            )
            today_rows = fills_result.all()

            # 연속 손실용: 최근 매도 체결 20건 (날짜 무관)
            recent_result = await db.execute(
                select(Fill, Order, Position)
                .join(Order, Fill.order_id == Order.id)
                .join(Position, Position.coin_id == Order.coin_id, isouter=True)
                .where(Order.side == "ask")
                .order_by(Fill.filled_at.desc())
                .limit(20)
            )
            recent_rows = recent_result.all()

        # daily_pnl: 매도가 - 평균매수가 기준 손익
        daily_pnl = 0.0
        for fill, order, pos in today_rows:
            if pos and pos.avg_entry_price > 0:
                daily_pnl += (fill.price - pos.avg_entry_price) * fill.volume - fill.fee

        # consecutive_losses: 최근 체결부터 역순으로 연속 손실 카운트
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
        async with self.session_factory() as db:
            # 코인 정보
            coin = await db.get(Coin, signal.coin_id)
            if not coin:
                return

            # 현재 포지션
            pos_result = await db.execute(
                select(Position).where(Position.coin_id == signal.coin_id)
            )
            position = pos_result.scalar_one_or_none()

            # 매수 신호인데 이미 포지션 있으면 스킵
            if signal.side == "buy" and position and position.qty > 0:
                await self._update_signal_status(db, signal, "rejected", "Already in position")
                return

            # 매도 신호인데 포지션 없으면 스킵
            if signal.side == "sell" and (not position or position.qty <= 0):
                await self._update_signal_status(db, signal, "rejected", "No position to sell")
                return

        # 계좌 잔고 조회
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

        # 현재가 조회 (entry_price 기준)
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

        # 위험 지표 계산
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

        # 수량 계산
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
            return

        final_qty = decision.adjusted_qty or qty

        # 주문 실행
        try:
            if signal.side == "buy":
                result = await self.upbit.place_order(
                    market=coin.market,
                    side="bid",
                    volume=final_qty,
                    price=None,
                    ord_type="market",  # 시장가 매수
                )
            else:
                result = await self.upbit.place_order(
                    market=coin.market,
                    side="ask",
                    volume=final_qty,
                    price=None,
                    ord_type="market",  # 시장가 매도
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
                await db.commit()

            logger.info(
                "Order placed: %s %s qty=%.6f uuid=%s",
                coin.market, signal.side, final_qty, result.get("uuid"),
            )

        except Exception as e:
            async with self.session_factory() as db:
                await self._update_signal_status(db, signal, "rejected", str(e))
            logger.error("Order failed: %s - %s", coin.market, e)

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

                        # 체결 처리
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

                            # 포지션 업데이트
                            await self._update_position(db, order, info)

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
                # 평균단가 재계산
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

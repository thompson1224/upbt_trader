"""체결 처리 + 리스크 지표 모듈 - 주문 동기화, Fill 반영, 일별 P&L 관리."""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from math import isclose
from zoneinfo import ZoneInfo

from sqlalchemy import select

from libs.db.models import Coin, Fill, Order, Position, RuntimeState, Signal

from .portfolio import (
    POSITION_SOURCE_STRATEGY,
    _resolve_protection_levels,
)

logger = logging.getLogger(__name__)

# ── 상수 ──────────────────────────────────────────────────────────────────────

RUNTIME_STATE_LOSS_STREAK_KEY = "risk.loss_streak"
RUNTIME_STATE_LOSS_STREAK_DATE_KEY = "risk.loss_streak.date"
RISK_LOSS_STREAK_REDIS_KEY = "risk:loss_streak"
RISK_LOSS_STREAK_DATE_REDIS_KEY = "risk:loss_streak:date"

# ── 순수 헬퍼 함수 ────────────────────────────────────────────────────────────


def _runtime_state_daily_pnl_key(now: datetime | None = None) -> str:
    kst = ZoneInfo("Asia/Seoul")
    ts = now.astimezone(kst) if now else datetime.now(tz=kst)
    return f"risk.daily_pnl.{ts.strftime('%Y%m%d')}"


def _current_kst_day_start_utc(now: datetime | None = None) -> datetime:
    kst = ZoneInfo("Asia/Seoul")
    current = now.astimezone(kst) if now else datetime.now(tz=kst)
    return current.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(
        timezone.utc
    )


def _risk_metric_date(now: datetime | None = None) -> str:
    kst = ZoneInfo("Asia/Seoul")
    ts = now.astimezone(kst) if now else datetime.now(tz=kst)
    return ts.strftime("%Y%m%d")


def _should_reset_loss_streak(stored_date: str | None, current_date: str) -> bool:
    return bool(stored_date) and stored_date != current_date


def _filter_new_trades(
    trades: list[dict],
    existing_trade_uuids: set[str],
) -> list[dict]:
    """이미 저장된 체결을 제외한 신규 체결만 반환."""
    return [
        trade
        for trade in trades
        if str(trade.get("uuid")) and str(trade.get("uuid")) not in existing_trade_uuids
    ]


def _summarize_trades(
    trades: list[dict],
    *,
    fallback_executed_volume: float = 0.0,
    fallback_executed_funds: float = 0.0,
) -> tuple[float, float, float, float]:
    """체결 목록에서 수량/체결대금/평균가/수수료를 계산."""
    if trades:
        executed_volume = sum(float(trade.get("volume", 0) or 0) for trade in trades)
        executed_funds = sum(float(trade.get("funds", 0) or 0) for trade in trades)
    else:
        executed_volume = fallback_executed_volume
        executed_funds = fallback_executed_funds
    avg_price = executed_funds / executed_volume if executed_volume > 0 else 0.0
    total_fee = sum(float(trade.get("funds", 0) or 0) * 0.0005 for trade in trades)
    return executed_volume, executed_funds, avg_price, total_fee


def _build_closed_trades_for_risk(fill_rows: list[dict]) -> list[dict]:
    open_lots: dict[str, list[dict]] = defaultdict(list)
    trades: list[dict] = []

    for row in fill_rows:
        market = row["market"]
        side = row["side"]
        volume = row["volume"]
        price = row["price"]
        fee = row["fee"]
        filled_at = row["filledAt"]

        if side == "bid":
            open_lots[market].append(
                {
                    "remainingQty": volume,
                    "remainingFunds": price * volume,
                    "remainingFee": fee,
                    "entryTs": filled_at,
                }
            )
            continue

        lots = open_lots.get(market)
        if not lots or volume <= 0:
            continue

        remaining_exit_qty = volume
        while (
            lots
            and remaining_exit_qty > 1e-9
            and not isclose(remaining_exit_qty, 0.0, abs_tol=1e-9)
        ):
            lot = lots[0]
            lot_qty = lot["remainingQty"]
            if lot_qty <= 1e-9 or isclose(lot_qty, 0.0, abs_tol=1e-9):
                lots.pop(0)
                continue

            matched_qty = min(remaining_exit_qty, lot_qty)
            matched_ratio = matched_qty / max(lot_qty, 1e-12)
            entry_funds = lot["remainingFunds"] * matched_ratio
            entry_fee = lot["remainingFee"] * matched_ratio
            exit_funds = price * matched_qty
            exit_fee = fee * (matched_qty / max(volume, 1e-12))
            gross_pnl = exit_funds - entry_funds
            net_pnl = gross_pnl - entry_fee - exit_fee

            trades.append({"exitTs": filled_at, "netPnl": net_pnl})

            lot["remainingQty"] -= matched_qty
            lot["remainingFunds"] -= entry_funds
            lot["remainingFee"] -= entry_fee
            remaining_exit_qty -= matched_qty

            if lot["remainingQty"] <= 1e-9 or isclose(
                lot["remainingQty"], 0.0, abs_tol=1e-9
            ):
                lots.pop(0)

    trades.sort(key=lambda trade: trade["exitTs"])
    return trades


def _risk_metrics_from_closed_trades(trades: list[dict]) -> tuple[float, int]:
    daily_pnl = sum(float(trade.get("netPnl", 0.0) or 0.0) for trade in trades)
    loss_streak = 0
    for trade in reversed(trades):
        net_pnl = float(trade.get("netPnl", 0.0) or 0.0)
        if net_pnl < 0:
            loss_streak += 1
            continue
        break
    return daily_pnl, loss_streak


def _parse_trade_filled_at(trade: dict) -> datetime:
    raw = trade.get("created_at")
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(tz=timezone.utc)


# ── FillProcessor 클래스 ──────────────────────────────────────────────────────


class FillProcessor:
    def __init__(self, *, session_factory, upbit, redis, settings):
        self.session_factory = session_factory
        self.upbit = upbit
        self.redis = redis
        self.settings = settings

    async def _compute_risk_metrics(self) -> tuple[float, int]:
        """오늘 체결 기준으로 리스크 지표를 재계산하고 Redis/DB에 반영."""
        current_date = _risk_metric_date()
        try:
            daily_pnl, loss_streak = await self._recalculate_risk_metrics_from_db()
            await self.redis.set(self._daily_pnl_redis_key(), daily_pnl)
            await self.redis.expire(self._daily_pnl_redis_key(), 60 * 60 * 48)
            await self.redis.set(RISK_LOSS_STREAK_REDIS_KEY, loss_streak)
            await self.redis.set(RISK_LOSS_STREAK_DATE_REDIS_KEY, current_date)
            await self._persist_risk_metrics_to_db(daily_pnl, loss_streak, current_date)
            return daily_pnl, loss_streak
        except Exception as e:
            logger.warning("Risk metric read failed: %s", e)
            daily_pnl, loss_streak, streak_date = await self._load_risk_metrics_from_db()
            if _should_reset_loss_streak(streak_date, current_date):
                await self._persist_risk_metrics_to_db(daily_pnl, 0, current_date)
                return daily_pnl, 0
            return daily_pnl, loss_streak

    @staticmethod
    def _daily_pnl_redis_key(now: datetime | None = None) -> str:
        kst = ZoneInfo("Asia/Seoul")
        ts = now.astimezone(kst) if now else datetime.now(tz=kst)
        return f"risk:daily_pnl:{ts.strftime('%Y%m%d')}"

    async def _record_trade_result(self, trade_pnl: float):
        """실현 손익 발생 후 DB 기준 리스크 지표를 재동기화."""
        try:
            await self._compute_risk_metrics()
        except Exception as e:
            logger.warning("Risk metric update failed: %s", e)
            daily_pnl, loss_streak, _streak_date = await self._load_risk_metrics_from_db()
            updated_daily_pnl = daily_pnl + trade_pnl
            updated_loss_streak = (loss_streak + 1) if trade_pnl < 0 else 0
            await self._persist_risk_metrics_to_db(
                updated_daily_pnl,
                updated_loss_streak,
                _risk_metric_date(),
            )

    async def _restore_runtime_state_from_db(self):
        """Redis 리스크 키가 비어 있으면 DB 백업값으로 복구."""
        daily_key = self._daily_pnl_redis_key()
        try:
            daily_raw, streak_raw, streak_date_raw = await self.redis.mget(
                daily_key,
                RISK_LOSS_STREAK_REDIS_KEY,
                RISK_LOSS_STREAK_DATE_REDIS_KEY,
            )
            if (
                daily_raw is not None
                or streak_raw is not None
                or streak_date_raw is not None
            ):
                return
        except Exception as e:
            logger.warning("Runtime state pre-check failed: %s", e)

        daily_pnl, loss_streak, streak_date = await self._load_risk_metrics_from_db()
        try:
            await self.redis.set(daily_key, daily_pnl)
            await self.redis.expire(daily_key, 60 * 60 * 48)
            await self.redis.set(RISK_LOSS_STREAK_REDIS_KEY, loss_streak)
            await self.redis.set(
                RISK_LOSS_STREAK_DATE_REDIS_KEY, streak_date or _risk_metric_date()
            )
        except Exception as e:
            logger.warning("Runtime state restore to Redis failed: %s", e)

    async def _recalculate_risk_metrics_from_db(self) -> tuple[float, int]:
        start_utc = _current_kst_day_start_utc()
        async with self.session_factory() as db:
            result = await db.execute(
                select(Fill, Order, Coin.market)
                .join(Order, Fill.order_id == Order.id)
                .join(Coin, Order.coin_id == Coin.id)
                .where(Fill.filled_at >= start_utc)
                .order_by(Fill.filled_at.asc(), Fill.id.asc())
            )
            rows = result.all()

        fill_rows = [
            {
                "market": market,
                "side": order.side,
                "price": fill.price,
                "volume": fill.volume,
                "fee": fill.fee,
                "filledAt": fill.filled_at,
            }
            for fill, order, market in rows
        ]
        trades = _build_closed_trades_for_risk(fill_rows)
        return _risk_metrics_from_closed_trades(trades)

    async def _load_risk_metrics_from_db(self) -> tuple[float, int, str | None]:
        async with self.session_factory() as db:
            daily_state = await db.get(RuntimeState, _runtime_state_daily_pnl_key())
            streak_state = await db.get(RuntimeState, RUNTIME_STATE_LOSS_STREAK_KEY)
            streak_date_state = await db.get(
                RuntimeState, RUNTIME_STATE_LOSS_STREAK_DATE_KEY
            )
            daily_pnl = float(daily_state.value) if daily_state else 0.0
            loss_streak = int(streak_state.value) if streak_state else 0
            streak_date = streak_date_state.value if streak_date_state else None
            return daily_pnl, loss_streak, streak_date

    async def _persist_risk_metrics_to_db(
        self,
        daily_pnl: float,
        loss_streak: int,
        loss_streak_date: str | None = None,
    ):
        async with self.session_factory() as db:
            daily_key = _runtime_state_daily_pnl_key()
            daily_state = await db.get(RuntimeState, daily_key)
            if daily_state is None:
                db.add(RuntimeState(key=daily_key, value=str(daily_pnl)))
            else:
                daily_state.value = str(daily_pnl)

            streak_state = await db.get(RuntimeState, RUNTIME_STATE_LOSS_STREAK_KEY)
            if streak_state is None:
                db.add(
                    RuntimeState(
                        key=RUNTIME_STATE_LOSS_STREAK_KEY, value=str(loss_streak)
                    )
                )
            else:
                streak_state.value = str(loss_streak)

            streak_date_key = RUNTIME_STATE_LOSS_STREAK_DATE_KEY
            streak_date_state = await db.get(RuntimeState, streak_date_key)
            streak_date_value = loss_streak_date or _risk_metric_date()
            if streak_date_state is None:
                db.add(RuntimeState(key=streak_date_key, value=streak_date_value))
            else:
                streak_date_state.value = streak_date_value

            await db.commit()

    async def _sync_pending_orders(self) -> bool:
        """미체결 주문 상태를 업비트와 동기화. 변경 여부를 반환."""
        changed = False
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
                        previous_state = db_order.state
                        db_order.state = new_state
                        changed = changed or (previous_state != new_state)
                        realized_pnl: float | None = None
                        executed_volume = 0.0
                        avg_price = 0.0

                        trades = info.get("trades", []) or []
                        existing_fill_result = await db.execute(
                            select(Fill.trade_uuid).where(Fill.order_id == order.id)
                        )
                        existing_trade_uuids = {
                            trade_uuid
                            for trade_uuid in existing_fill_result.scalars().all()
                        }
                        new_trades = _filter_new_trades(trades, existing_trade_uuids)

                        if new_trades:
                            executed_volume, _executed_funds, avg_price, _total_fee = (
                                _summarize_trades(new_trades)
                            )
                            for trade in new_trades:
                                fill = Fill(
                                    order_id=order.id,
                                    trade_uuid=trade["uuid"],
                                    price=float(trade["price"]),
                                    volume=float(trade["volume"]),
                                    fee=float(trade.get("funds", 0) or 0) * 0.0005,
                                    filled_at=_parse_trade_filled_at(trade),
                                )
                                db.add(fill)

                            realized_pnl = await self._apply_fill_delta(
                                db, order, new_trades
                            )
                            changed = True

                            try:
                                event_type = (
                                    "order_filled"
                                    if new_state == "done"
                                    else "order_partially_filled"
                                )
                                await self.redis.publish(
                                    "upbit:trade_event",
                                    json.dumps(
                                        {
                                            "type": event_type,
                                            "market": "",
                                            "side": order.side,
                                            "price": avg_price,
                                            "volume": executed_volume,
                                        }
                                    ),
                                )
                            except Exception:
                                pass

                        await db.commit()
                        if realized_pnl is not None:
                            await self._record_trade_result(realized_pnl)
            except Exception as e:
                logger.warning(
                    "Order sync failed for %s: %s", order.exchange_order_id, e
                )

        return changed

    async def _apply_fill_delta(
        self, db, order: Order, trades: list[dict]
    ) -> float | None:
        """신규 체결분만 포지션에 반영. 매도 체결이면 실현손익을 반환."""
        executed_volume, executed_funds, avg_price, total_fee = _summarize_trades(trades)
        if executed_volume <= 0:
            return None

        pos_result = await db.execute(
            select(Position).where(Position.coin_id == order.coin_id)
        )
        position = pos_result.scalar_one_or_none()

        if order.side == "bid":  # 매수
            if position:
                total_qty = position.qty + executed_volume
                position.avg_entry_price = (
                    position.avg_entry_price * position.qty
                    + avg_price * executed_volume
                ) / total_qty
                position.qty = total_qty
            else:
                position = Position(
                    coin_id=order.coin_id,
                    qty=executed_volume,
                    avg_entry_price=avg_price,
                    source=POSITION_SOURCE_STRATEGY,
                )
                db.add(position)
            position.source = POSITION_SOURCE_STRATEGY
            await self._apply_signal_protection(db, order, position)
            return None
        elif order.side == "ask" and position:  # 매도
            pnl = (avg_price - position.avg_entry_price) * executed_volume
            realized_pnl = pnl - total_fee
            position.realized_pnl += realized_pnl
            position.qty = max(0, position.qty - executed_volume)
            if position.qty <= 0:
                position.stop_loss = None
                position.take_profit = None
                await self._clear_position_source_override(db, order.coin_id)
            return realized_pnl
        return None

    async def _apply_signal_protection(
        self, db, order: Order, position: Position | None
    ):
        """매수 체결 후 신호에 담긴 SL/TP를 실제 포지션에 반영."""
        if not position or not order.signal_id:
            return

        signal = await db.get(Signal, order.signal_id)
        if not signal:
            return

        stop_loss, take_profit = _resolve_protection_levels(
            position.avg_entry_price,
            signal.suggested_stop_loss,
            signal.suggested_take_profit,
            self.settings.risk_default_stop_loss_pct,
            self.settings.risk_default_take_profit_pct,
        )
        if position.stop_loss is None:
            position.stop_loss = stop_loss
        if position.take_profit is None:
            position.take_profit = take_profit

    async def _clear_position_source_override(self, db, coin_id: int) -> None:
        from .portfolio import _position_management_key
        state = await db.get(RuntimeState, _position_management_key(coin_id))
        if state is not None:
            await db.delete(state)

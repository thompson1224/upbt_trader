"""포지션 보호 모듈 - SL/TP 모니터링, 중복 청산 방지, 시장가 매도 실행."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from libs.db.models import Coin, Order, Position

from .portfolio import (
    POSITION_SOURCE_EXTERNAL,
    _is_external_position_stop_loss_enabled,
    _should_enforce_position_protection,
)

logger = logging.getLogger(__name__)


class PositionGuard:
    def __init__(self, *, session_factory, upbit, redis, settings):
        self.session_factory = session_factory
        self.upbit = upbit
        self.redis = redis
        self.settings = settings

    async def _is_external_position_stop_loss_enabled(self) -> bool:
        return await _is_external_position_stop_loss_enabled(self.redis)

    async def _check_all_positions_sl_tp(self) -> list[dict]:
        external_stop_loss_enabled = await self._is_external_position_stop_loss_enabled()
        async with self.session_factory() as db:
            result = await db.execute(
                select(Position, Coin)
                .join(Coin, Position.coin_id == Coin.id)
                .where(Position.qty > 0)
            )
            rows = result.all()

        price_map = await self.upbit.get_tickers(
            [coin.market for _position, coin in rows]
        )
        portfolio_rows: list[dict] = []
        for position, coin in rows:
            try:
                price_row = await self._check_position_sl_tp(
                    position,
                    coin,
                    price_map.get(coin.market),
                    external_stop_loss_enabled,
                )
                if price_row:
                    portfolio_rows.append(price_row)
            except Exception as e:
                logger.warning("SL/TP check failed for %s: %s", coin.market, e)
        return portfolio_rows

    async def _check_position_sl_tp(
        self,
        position: Position,
        coin: Coin,
        current_price: float | None,
        external_stop_loss_enabled: bool,
    ) -> dict | None:
        """단일 포지션 SL/TP 확인 + 미실현 손익 갱신."""
        if not current_price or current_price <= 0:
            return None

        unrealized_pnl = (current_price - position.avg_entry_price) * position.qty
        trigger_reason: str | None = None

        # 미실현 손익 갱신 + SL/TP 트리거 시 원자적 클레임 설정
        async with self.session_factory() as db:
            db_pos = await db.get(Position, position.id)
            if not db_pos or db_pos.qty <= 0:
                return None  # 이미 청산됨
            if db_pos.liquidating:
                return None  # 이미 청산 진행 중
            if db_pos.source == POSITION_SOURCE_EXTERNAL:
                if db_pos.take_profit is not None:
                    db_pos.take_profit = None
                if not external_stop_loss_enabled and db_pos.stop_loss is not None:
                    db_pos.stop_loss = None
            if (
                db_pos.source == POSITION_SOURCE_EXTERNAL
                and (db_pos.stop_loss is not None or db_pos.take_profit is not None)
                and not external_stop_loss_enabled
            ):
                logger.warning(
                    "Clearing stale protection from external position %s (coin_id=%s)",
                    coin.market,
                    position.coin_id,
                )

            if _should_enforce_position_protection(
                db_pos.source,
                external_stop_loss_enabled,
                db_pos.stop_loss,
                db_pos.take_profit,
            ):
                sl_triggered = (
                    db_pos.stop_loss is not None and current_price <= db_pos.stop_loss
                )
                tp_triggered = (
                    db_pos.take_profit is not None
                    and current_price >= db_pos.take_profit
                )
                if sl_triggered:
                    trigger_reason = (
                        f"SL triggered: {current_price:.0f} <= {db_pos.stop_loss:.0f}"
                    )
                elif tp_triggered:
                    trigger_reason = (
                        f"TP triggered: {current_price:.0f} >= {db_pos.take_profit:.0f}"
                    )

            # 트리거 조건 충족 시 liquidating=True를 같은 트랜잭션에서 원자적으로 설정
            if trigger_reason:
                db_pos.liquidating = True

            db_pos.unrealized_pnl = unrealized_pnl
            await db.commit()
            position.stop_loss = db_pos.stop_loss
            position.take_profit = db_pos.take_profit

        try:
            await self.redis.publish(
                "upbit:position_update",
                json.dumps({
                    "coinId": position.coin_id,
                    "market": coin.market,
                    "qty": position.qty,
                    "avgEntryPrice": position.avg_entry_price,
                    "currentPrice": current_price,
                    "unrealizedPnl": unrealized_pnl,
                    "stopLoss": position.stop_loss,
                    "takeProfit": position.take_profit,
                }),
            )
        except Exception as e:
            logger.warning("Failed to publish position_update: %s", e)

        if trigger_reason:
            logger.info("Position close triggered for %s: %s", coin.market, trigger_reason)
            await self._execute_sl_tp_sell(position, coin, trigger_reason)

        return {
            "coinId": position.coin_id,
            "market": coin.market,
            "qty": position.qty,
            "currentPrice": current_price,
            "marketValue": current_price * position.qty,
            "unrealizedPnl": unrealized_pnl,
        }

    async def _clear_liquidating_flag(self, position_id: int) -> None:
        """주문 실패 시 liquidating 플래그를 해제하여 다음 루프에서 재시도 가능하게 함."""
        try:
            async with self.session_factory() as db:
                db_pos = await db.get(Position, position_id)
                if db_pos:
                    db_pos.liquidating = False
                    await db.commit()
        except Exception as e:
            logger.error(
                "Failed to clear liquidating flag for position_id=%d: %s", position_id, e
            )

    async def _execute_sl_tp_sell(self, position: Position, coin: Coin, reason: str):
        """
        SL/TP 조건 충족 시 시장가 매도 직접 실행.
        주의: auto_trade 스위치와 무관하게 항상 실행 (손실 방지 목적).
        호출 전제: position.liquidating == True (원자적 클레임 완료 상태)
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
            # 주문 실패 시 클레임 해제 → 다음 루프에서 재시도
            await self._clear_liquidating_flag(position.id)
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

        try:
            event_type = "sl_triggered" if "SL" in reason else "tp_triggered"
            current_price = await self.upbit.get_ticker(coin.market)
            await self.redis.publish(
                "upbit:trade_event",
                json.dumps({"type": event_type, "market": coin.market, "price": current_price}),
            )
        except Exception:
            pass

"""포트폴리오 관리 모듈 - 포지션 동기화, 스냅샷, 보호 레벨 계산.

다른 execution_service 서브모듈은 이 파일을 import할 수 있으나,
이 파일은 execution_service 내 다른 모듈을 절대 import하지 않는다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from libs.db.models import Coin, Order, Position, RuntimeState
from libs.db.session import get_session_factory

logger = logging.getLogger(__name__)

# ── 상수 ──────────────────────────────────────────────────────────────────────

POSITION_SOURCE_STRATEGY = "strategy"
POSITION_SOURCE_EXTERNAL = "external"
POSITION_SOURCE_OVERRIDE_KEY_PREFIX = "position.management."
EXTERNAL_POSITION_SL_REDIS_KEY = "settings:external_position_sl:enabled"
BALANCE_SYNC_INTERVAL_SEC = 30
EQUITY_CURVE_MAX_POINTS = 500
PORTFOLIO_EQUITY_CURVE_KEY = "portfolio:equity_curve"
PORTFOLIO_LATEST_SNAPSHOT_KEY = "portfolio:latest_snapshot"
UPBIT_FEE_RATE = 0.0005

# ── 순수 헬퍼 함수 ────────────────────────────────────────────────────────────


def _extract_exchange_position_rows(
    balances: list[dict],
) -> tuple[float, dict[str, dict[str, float]]]:
    """업비트 잔고 목록에서 KRW와 코인 포지션 정보를 추출."""
    available_krw = 0.0
    positions: dict[str, dict[str, float]] = {}

    for item in balances:
        currency = str(item.get("currency", "")).upper()
        balance = float(item.get("balance", 0) or 0)
        locked = float(item.get("locked", 0) or 0)
        total_qty = balance + locked

        if currency == "KRW":
            available_krw = balance
            continue

        if total_qty <= 0:
            continue

        positions[currency] = {
            "qty": total_qty,
            "avg_entry_price": float(item.get("avg_buy_price", 0) or 0),
        }

    return available_krw, positions


def _extract_total_krw_balance(balances: list[dict]) -> float:
    """KRW 총액(balance + locked). 총자산 계산용."""
    for item in balances:
        currency = str(item.get("currency", "")).upper()
        if currency != "KRW":
            continue
        balance = float(item.get("balance", 0) or 0)
        locked = float(item.get("locked", 0) or 0)
        return balance + locked
    return 0.0


def _default_protection_levels(
    entry_price: float,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> tuple[float | None, float | None]:
    """평단 기준 기본 SL/TP 레벨 계산."""
    if entry_price <= 0:
        return None, None

    safe_stop_loss_pct = min(max(stop_loss_pct, 0.0), 0.99)
    safe_take_profit_pct = max(take_profit_pct, 0.0)
    return (
        entry_price * (1 - safe_stop_loss_pct),
        entry_price * (1 + safe_take_profit_pct),
    )


def _resolve_protection_levels(
    entry_price: float,
    suggested_stop_loss: float | None,
    suggested_take_profit: float | None,
    default_stop_loss_pct: float,
    default_take_profit_pct: float,
) -> tuple[float | None, float | None]:
    """신호 제안값이 없으면 기본 보호 레벨로 보완."""
    default_stop_loss, default_take_profit = _default_protection_levels(
        entry_price,
        default_stop_loss_pct,
        default_take_profit_pct,
    )
    return (
        suggested_stop_loss if suggested_stop_loss is not None else default_stop_loss,
        suggested_take_profit
        if suggested_take_profit is not None
        else default_take_profit,
    )


def _resolve_synced_position_protection_levels(
    entry_price: float,
    default_stop_loss_pct: float,
    default_take_profit_pct: float,
    strategy_managed: bool,
    external_stop_loss_enabled: bool,
) -> tuple[float | None, float | None]:
    """거래소 동기화 포지션의 기본 보호 레벨 계산."""
    stop_loss, take_profit = _default_protection_levels(
        entry_price,
        default_stop_loss_pct,
        default_take_profit_pct,
    )
    if strategy_managed:
        return stop_loss, take_profit
    if external_stop_loss_enabled:
        return stop_loss, None
    return None, None


def _should_enforce_position_protection(
    source: str,
    external_stop_loss_enabled: bool,
    stop_loss: float | None,
    take_profit: float | None,
) -> bool:
    """자동 보호 집행 여부."""
    if source == POSITION_SOURCE_STRATEGY:
        return stop_loss is not None or take_profit is not None
    if source == POSITION_SOURCE_EXTERNAL:
        return external_stop_loss_enabled and stop_loss is not None
    return False


def _position_source_from_strategy_managed(strategy_managed: bool) -> str:
    return POSITION_SOURCE_STRATEGY if strategy_managed else POSITION_SOURCE_EXTERNAL


def _position_management_key(coin_id: int) -> str:
    return f"{POSITION_SOURCE_OVERRIDE_KEY_PREFIX}{coin_id}"


def _resolve_position_source(
    strategy_managed: bool,
    source_override: str | None = None,
) -> str:
    if source_override in {POSITION_SOURCE_STRATEGY, POSITION_SOURCE_EXTERNAL}:
        return source_override
    return _position_source_from_strategy_managed(strategy_managed)


async def _is_external_position_stop_loss_enabled(redis) -> bool:
    """외부 보유분 자동 손절 설정 조회. 기본값은 False."""
    try:
        val = await redis.get(EXTERNAL_POSITION_SL_REDIS_KEY)
        return val is not None and val.decode() == "1"
    except Exception as e:
        logger.warning("Failed to read external position SL flag from Redis: %s", e)
        return False


# ── PortfolioManager 클래스 ───────────────────────────────────────────────────


class PortfolioManager:
    def __init__(self, *, session_factory, upbit, redis, settings, compute_risk_metrics):
        self.session_factory = session_factory
        self.upbit = upbit
        self.redis = redis
        self.settings = settings
        self._compute_risk_metrics = compute_risk_metrics

    async def _is_external_position_stop_loss_enabled(self) -> bool:
        return await _is_external_position_stop_loss_enabled(self.redis)

    async def _sync_exchange_positions_once(self):
        balances = await self.upbit.get_balances()
        external_stop_loss_enabled = await self._is_external_position_stop_loss_enabled()
        await self._sync_positions_from_exchange(balances, external_stop_loss_enabled)
        await self._store_portfolio_snapshot([], balances=balances)

    async def _sync_positions_from_exchange(
        self,
        balances: list[dict],
        external_stop_loss_enabled: bool,
    ):
        """업비트 실잔고를 기준으로 로컬 positions를 보정."""
        _available_krw, exchange_positions = _extract_exchange_position_rows(balances)
        currencies = list(exchange_positions.keys())

        async with self.session_factory() as db:
            coin_map: dict[str, Coin] = {}
            if currencies:
                coin_result = await db.execute(
                    select(Coin).where(
                        Coin.base_currency.in_(currencies),
                        Coin.quote_currency == "KRW",
                    )
                )
                coin_map = {
                    coin.base_currency.upper(): coin
                    for coin in coin_result.scalars().all()
                }

            existing_result = await db.execute(select(Position))
            existing_positions = {
                pos.coin_id: pos for pos in existing_result.scalars().all()
            }
            synced_coin_ids: set[int] = set()

            for currency, payload in exchange_positions.items():
                coin = coin_map.get(currency)
                if not coin:
                    continue

                synced_coin_ids.add(coin.id)
                position = existing_positions.get(coin.id)
                strategy_managed = await self._has_strategy_buy_history(db, coin.id)
                source_override = await self._get_position_source_override(db, coin.id)
                source = _resolve_position_source(strategy_managed, source_override)
                strategy_managed = source == POSITION_SOURCE_STRATEGY
                stop_loss, take_profit = _resolve_synced_position_protection_levels(
                    payload["avg_entry_price"],
                    default_stop_loss_pct=self.settings.risk_default_stop_loss_pct,
                    default_take_profit_pct=self.settings.risk_default_take_profit_pct,
                    strategy_managed=strategy_managed,
                    external_stop_loss_enabled=external_stop_loss_enabled,
                )
                if position is None:
                    db.add(
                        Position(
                            coin_id=coin.id,
                            qty=payload["qty"],
                            avg_entry_price=payload["avg_entry_price"],
                            unrealized_pnl=0.0,
                            realized_pnl=0.0,
                            source=source,
                            stop_loss=stop_loss,
                            take_profit=take_profit,
                        )
                    )
                    continue

                position.qty = payload["qty"]
                position.avg_entry_price = payload["avg_entry_price"]
                position.unrealized_pnl = 0.0
                position.source = source
                if stop_loss is not None and position.stop_loss is None:
                    position.stop_loss = stop_loss
                if strategy_managed and position.take_profit is None:
                    position.take_profit = take_profit
                if not strategy_managed and not external_stop_loss_enabled:
                    position.stop_loss = None
                if not strategy_managed:
                    position.take_profit = None

            for coin_id, position in existing_positions.items():
                if coin_id in synced_coin_ids:
                    continue
                if position.qty > 0:
                    position.qty = 0.0
                    position.avg_entry_price = 0.0
                    position.unrealized_pnl = 0.0
                    position.stop_loss = None
                    position.take_profit = None
                    await self._clear_position_source_override(db, coin_id)

            await db.commit()

    async def _has_strategy_buy_history(self, db, coin_id: int) -> bool:
        result = await db.execute(
            select(Order.id)
            .where(
                Order.coin_id == coin_id,
                Order.side == "bid",
                Order.signal_id.is_not(None),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _get_position_source_override(self, db, coin_id: int) -> str | None:
        state = await db.get(RuntimeState, _position_management_key(coin_id))
        if not state:
            return None
        if state.value in {POSITION_SOURCE_STRATEGY, POSITION_SOURCE_EXTERNAL}:
            return state.value
        return None

    async def _clear_position_source_override(self, db, coin_id: int) -> None:
        state = await db.get(RuntimeState, _position_management_key(coin_id))
        if state is not None:
            await db.delete(state)

    async def _store_portfolio_snapshot(
        self, portfolio_rows: list[dict], balances: list[dict] | None = None
    ):
        """실시간 포트폴리오 스냅샷과 자산곡선을 Redis에 저장."""
        try:
            if balances is None:
                balances = await self.upbit.get_balances()
            available_krw, _exchange_positions = _extract_exchange_position_rows(balances)
            total_krw = _extract_total_krw_balance(balances)
        except Exception as e:
            logger.warning("Portfolio snapshot skipped: balance fetch failed: %s", e)
            return

        if not portfolio_rows:
            async with self.session_factory() as db:
                result = await db.execute(
                    select(Position, Coin)
                    .join(Coin, Position.coin_id == Coin.id)
                    .where(Position.qty > 0)
                )
                rows = result.all()

            price_map = await self.upbit.get_tickers(
                [coin.market for position, coin in rows if position.qty > 0]
            )
            for position, coin in rows:
                current_price = price_map.get(coin.market)
                if current_price and current_price > 0:
                    portfolio_rows.append(
                        {
                            "coinId": position.coin_id,
                            "market": coin.market,
                            "qty": position.qty,
                            "currentPrice": current_price,
                            "marketValue": current_price * position.qty,
                            "unrealizedPnl": (current_price - position.avg_entry_price)
                            * position.qty,
                        }
                    )

        position_value = sum(row["marketValue"] for row in portfolio_rows)
        daily_pnl, _ = await self._compute_risk_metrics()
        snapshot = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "equity": total_krw + position_value,
            "availableKrw": available_krw,
            "positionValue": position_value,
            "dailyPnl": daily_pnl,
            "openPositions": len(portfolio_rows),
        }

        try:
            payload = json.dumps(snapshot)
            await self.redis.rpush(PORTFOLIO_EQUITY_CURVE_KEY, payload)
            await self.redis.ltrim(PORTFOLIO_EQUITY_CURVE_KEY, -EQUITY_CURVE_MAX_POINTS, -1)
            await self.redis.set(PORTFOLIO_LATEST_SNAPSHOT_KEY, payload)
            await self.redis.publish(
                "upbit:position_update",
                json.dumps({"type": "portfolio_snapshot", **snapshot}),
            )
        except Exception as e:
            logger.warning("Portfolio snapshot store failed: %s", e)

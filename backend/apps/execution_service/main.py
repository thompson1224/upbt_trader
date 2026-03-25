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
from libs.db.models import Signal, Order, Fill, Position, Coin, RuntimeState
from libs.upbit.rest_client import UpbitRestClient
from apps.risk_service.guards.pre_trade_guard import (
    PreTradeRiskGuard, PositionSizer, AccountState,
)

# Upbit 시장 경보 값 (이 값만 True 처리)
_MARKET_WARNING_VALUES = {"CAUTION", "WARNING", "PRICE_FLUCTUATIONS", "TRADING_VOLUME_SOARING"}
POSITION_SOURCE_STRATEGY = "strategy"
POSITION_SOURCE_EXTERNAL = "external"
POSITION_SOURCE_OVERRIDE_KEY_PREFIX = "position.management."
EXTERNAL_POSITION_SL_REDIS_KEY = "settings:external_position_sl:enabled"
MANUAL_TEST_MODE_REDIS_KEY = "settings:manual_test_mode:enabled"
MANUAL_TEST_STRATEGY_ID = "manual-test"


def _is_market_warning(raw: str | None) -> bool:
    """Upbit market_warning 문자열 → bool. "NONE"과 None은 False."""
    return raw in _MARKET_WARNING_VALUES


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 5         # 신호 폴링 주기
ORDER_SYNC_INTERVAL_SEC = 10  # 미체결 주문 동기화 주기
SL_TP_INTERVAL_SEC = 10       # SL/TP 모니터 주기
BALANCE_SYNC_INTERVAL_SEC = 30
EQUITY_CURVE_MAX_POINTS = 500
PORTFOLIO_EQUITY_CURVE_KEY = "portfolio:equity_curve"
PORTFOLIO_LATEST_SNAPSHOT_KEY = "portfolio:latest_snapshot"
RUNTIME_STATE_LOSS_STREAK_KEY = "risk.loss_streak"
RUNTIME_STATE_LOSS_STREAK_DATE_KEY = "risk.loss_streak.date"
UPBIT_FEE_RATE = 0.0005
RISK_LOSS_STREAK_REDIS_KEY = "risk:loss_streak"
RISK_LOSS_STREAK_DATE_REDIS_KEY = "risk:loss_streak:date"

# 수수료(왕복 0.1%) 대비 최소 기대 수익률
MIN_PROFIT_THRESHOLD = 0.003  # 0.3% 미만 기대 수익 신호 거부


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


def _resolve_market_buy_krw_amount(
    *,
    requested_qty: float,
    entry_price: float,
    available_krw: float,
    min_order_krw: float,
    fee_rate: float = UPBIT_FEE_RATE,
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
        suggested_take_profit if suggested_take_profit is not None else default_take_profit,
    )


def _resolve_synced_position_protection_levels(
    entry_price: float,
    default_stop_loss_pct: float,
    default_take_profit_pct: float,
    strategy_managed: bool,
    external_stop_loss_enabled: bool,
) -> tuple[float | None, float | None]:
    """거래소 동기화 포지션의 기본 보호 레벨 계산.

    외부 보유분은 사용자의 명시적 의도 없이 자동 청산되면 안 되므로
    전략 매수 이력이 없는 경우 기본 TP는 비활성화하고,
    외부 손절 보호를 명시적으로 켠 경우에만 기본 SL을 부여한다.
    """
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


def _runtime_state_daily_pnl_key(now: datetime | None = None) -> str:
    kst = ZoneInfo("Asia/Seoul")
    ts = now.astimezone(kst) if now else datetime.now(tz=kst)
    return f"risk.daily_pnl.{ts.strftime('%Y%m%d')}"


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


def _parse_trade_filled_at(trade: dict) -> datetime:
    raw = trade.get("created_at")
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(tz=timezone.utc)


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
        await self._restore_runtime_state_from_db()
        daily_pnl, loss_streak = await self._compute_risk_metrics()
        await self._persist_risk_metrics_to_db(daily_pnl, loss_streak)
        try:
            await self._sync_exchange_positions_once()
        except Exception as e:
            logger.warning("Initial exchange position sync failed: %s", e)

        await asyncio.gather(
            self._signal_poll_loop(),
            self._order_sync_loop(),
            self._sl_tp_monitor_loop(),
            self._balance_sync_loop(),
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

    async def _is_external_position_stop_loss_enabled(self) -> bool:
        """외부 보유분 자동 손절 설정 조회. 기본값은 False."""
        try:
            val = await self._redis.get(EXTERNAL_POSITION_SL_REDIS_KEY)
            return val is not None and val.decode() == "1"
        except Exception as e:
            logger.warning("Failed to read external position SL flag from Redis: %s", e)
            return False

    async def _is_manual_test_mode_enabled(self) -> bool:
        """수동 주문 테스트 모드 조회. 기본값은 False."""
        try:
            val = await self._redis.get(MANUAL_TEST_MODE_REDIS_KEY)
            return val is not None and val.decode() == "1"
        except Exception as e:
            logger.warning("Failed to read manual test mode flag from Redis: %s", e)
            return False

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
        """Redis에 누적한 오늘 손익과 연속 손실 횟수를 조회."""
        current_date = _risk_metric_date()
        try:
            daily_raw, streak_raw, streak_date_raw = await self._redis.mget(
                self._daily_pnl_redis_key(),
                RISK_LOSS_STREAK_REDIS_KEY,
                RISK_LOSS_STREAK_DATE_REDIS_KEY,
            )
            daily_pnl = float(daily_raw.decode()) if daily_raw else 0.0
            loss_streak = int(streak_raw.decode()) if streak_raw else 0
            streak_date = streak_date_raw.decode() if streak_date_raw else None
            if daily_raw is None and streak_raw is None and streak_date_raw is None:
                daily_pnl, loss_streak, streak_date = await self._load_risk_metrics_from_db()
            if _should_reset_loss_streak(streak_date, current_date):
                loss_streak = 0
                await self._redis.set(RISK_LOSS_STREAK_REDIS_KEY, 0)
                await self._redis.set(RISK_LOSS_STREAK_DATE_REDIS_KEY, current_date)
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
        """실현 손익과 연속 손실 횟수를 Redis에 누적."""
        try:
            daily_key = self._daily_pnl_redis_key()
            current_date = _risk_metric_date()
            streak_date_raw = await self._redis.get(RISK_LOSS_STREAK_DATE_REDIS_KEY)
            streak_date = streak_date_raw.decode() if streak_date_raw else None
            if _should_reset_loss_streak(streak_date, current_date):
                await self._redis.set(RISK_LOSS_STREAK_REDIS_KEY, 0)
            await self._redis.incrbyfloat(daily_key, trade_pnl)
            await self._redis.expire(daily_key, 60 * 60 * 48)
            if trade_pnl < 0:
                await self._redis.incr(RISK_LOSS_STREAK_REDIS_KEY)
            else:
                await self._redis.set(RISK_LOSS_STREAK_REDIS_KEY, 0)
            await self._redis.set(RISK_LOSS_STREAK_DATE_REDIS_KEY, current_date)
            daily_pnl, loss_streak = await self._compute_risk_metrics()
            await self._persist_risk_metrics_to_db(daily_pnl, loss_streak, current_date)
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
            daily_raw, streak_raw, streak_date_raw = await self._redis.mget(
                daily_key,
                RISK_LOSS_STREAK_REDIS_KEY,
                RISK_LOSS_STREAK_DATE_REDIS_KEY,
            )
            if daily_raw is not None or streak_raw is not None or streak_date_raw is not None:
                return
        except Exception as e:
            logger.warning("Runtime state pre-check failed: %s", e)

        daily_pnl, loss_streak, streak_date = await self._load_risk_metrics_from_db()
        try:
            await self._redis.set(daily_key, daily_pnl)
            await self._redis.expire(daily_key, 60 * 60 * 48)
            await self._redis.set(RISK_LOSS_STREAK_REDIS_KEY, loss_streak)
            await self._redis.set(RISK_LOSS_STREAK_DATE_REDIS_KEY, streak_date or _risk_metric_date())
        except Exception as e:
            logger.warning("Runtime state restore to Redis failed: %s", e)

    async def _load_risk_metrics_from_db(self) -> tuple[float, int, str | None]:
        async with self.session_factory() as db:
            daily_state = await db.get(RuntimeState, _runtime_state_daily_pnl_key())
            streak_state = await db.get(RuntimeState, RUNTIME_STATE_LOSS_STREAK_KEY)
            streak_date_state = await db.get(RuntimeState, RUNTIME_STATE_LOSS_STREAK_DATE_KEY)
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
                db.add(RuntimeState(key=RUNTIME_STATE_LOSS_STREAK_KEY, value=str(loss_streak)))
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

    async def _balance_sync_loop(self):
        """거래소 실잔고를 주기적으로 로컬 positions에 동기화."""
        while not self._kill_switch:
            try:
                await self._sync_exchange_positions_once()
            except Exception as e:
                logger.warning("Exchange position sync failed: %s", e)
            await asyncio.sleep(BALANCE_SYNC_INTERVAL_SEC)

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
                    db.add(Position(
                        coin_id=coin.id,
                        qty=payload["qty"],
                        avg_entry_price=payload["avg_entry_price"],
                        unrealized_pnl=0.0,
                        realized_pnl=0.0,
                        source=source,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                    ))
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

    async def _execute_signal(self, signal: Signal):
        auto_trade_enabled = await self._is_auto_trade_enabled()
        manual_test_mode_enabled = await self._is_manual_test_mode_enabled()
        manual_test_signal = _is_manual_test_signal(signal.strategy_id)

        if not _can_execute_signal(
            strategy_id=signal.strategy_id,
            auto_trade_enabled=auto_trade_enabled,
            manual_test_mode_enabled=manual_test_mode_enabled,
        ):
            logger.info(
                "Execution disabled for signal %s: auto_trade=%s manual_test_mode=%s strategy=%s",
                signal.id,
                auto_trade_enabled,
                manual_test_mode_enabled,
                signal.strategy_id,
            )
            return  # 상태 "new" 유지 → 재활성화 시 재처리

        # ── 최소 수익 임계값 확인 (수수료 보전) ─────────────
        expected_profit = abs(signal.final_score) * 0.02
        if (not manual_test_signal) and expected_profit < MIN_PROFIT_THRESHOLD:
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
            pos_count_result = await db.execute(
                select(Position).where(Position.qty > 0)
            )
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
                            db,
                            signal,
                            "rejected",
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
                        db,
                        signal,
                        "rejected",
                        f"Manual test sell below minimum {self.sizer.MIN_ORDER_KRW} KRW",
                    )
                return
            if _is_market_warning(coin.market_warning):
                async with self.session_factory() as db:
                    await self._update_signal_status(
                        db,
                        signal,
                        "rejected",
                        f"Market warning active for {coin.market}",
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
                # 리스크 기반 수량이 최소주문금액 미달 시 잔액이 충분하면 최소 주문으로 폴백
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
                # 업비트 시장가 매수: ord_type="price" + price=KRW금액
                krw_amount = _resolve_market_buy_krw_amount(
                    requested_qty=final_qty,
                    entry_price=entry_price,
                    available_krw=available_krw,
                    min_order_krw=self.sizer.MIN_ORDER_KRW,
                )
                if krw_amount < self.sizer.MIN_ORDER_KRW:
                    async with self.session_factory() as db:
                        await self._update_signal_status(
                            db,
                            signal,
                            "rejected",
                            "Insufficient KRW after fee buffer",
                        )
                    return
                order_volume = krw_amount / entry_price
                result = await self.upbit.place_order(
                    market=coin.market,
                    side="bid",
                    volume=None,
                    price=krw_amount,
                    ord_type="price",
                )
            else:
                # 업비트 시장가 매도: ord_type="market" + volume=코인수량
                order_volume = final_qty
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
                    ord_type="price" if signal.side == "buy" else "market",
                    price=entry_price,
                    volume=order_volume,
                    state=result.get("state", "wait"),
                    requested_at=datetime.now(tz=timezone.utc),
                )
                db.add(order)
                await self._update_signal_status(db, signal, "executed", None)
                await db.commit()

            logger.info(
                "Order placed: %s %s qty=%.6f uuid=%s",
                coin.market, signal.side, order_volume, result.get("uuid"),
            )

            # 주문 접수 이벤트 브로드캐스트
            try:
                await self._redis.publish("upbit:trade_event", json.dumps({
                    "type": "order_placed",
                    "market": coin.market,
                    "side": "bid" if signal.side == "buy" else "ask",
                    "price": entry_price,
                    "volume": order_volume,
                }))
            except Exception:
                pass

        except Exception as e:
            async with self.session_factory() as db:
                await self._update_signal_status(db, signal, "rejected", str(e))
            try:
                await self._redis.publish("upbit:trade_event", json.dumps({
                    "type": "order_failed",
                    "market": coin.market,
                    "side": "bid" if signal.side == "buy" else "ask",
                    "reason": str(e),
                    "signalId": signal.id,
                }))
            except Exception:
                pass
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
                            trade_uuid for trade_uuid in existing_fill_result.scalars().all()
                        }
                        new_trades = _filter_new_trades(trades, existing_trade_uuids)

                        if new_trades:
                            executed_volume, _executed_funds, avg_price, _total_fee = _summarize_trades(new_trades)
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

                            realized_pnl = await self._apply_fill_delta(db, order, new_trades)
                            changed = True

                            # 체결 이벤트 브로드캐스트
                            try:
                                event_type = "order_filled" if new_state == "done" else "order_partially_filled"
                                await self._redis.publish("upbit:trade_event", json.dumps({
                                    "type": event_type,
                                    "market": "",
                                    "side": order.side,
                                    "price": avg_price,
                                    "volume": executed_volume,
                                }))
                            except Exception:
                                pass

                        await db.commit()
                        if realized_pnl is not None:
                            await self._record_trade_result(realized_pnl)
            except Exception as e:
                logger.warning("Order sync failed for %s: %s", order.exchange_order_id, e)

        if changed:
            await self._store_portfolio_snapshot([])

    async def _apply_fill_delta(self, db, order: Order, trades: list[dict]) -> float | None:
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
                    position.avg_entry_price * position.qty + avg_price * executed_volume
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

    async def _apply_signal_protection(self, db, order: Order, position: Position | None):
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
        external_stop_loss_enabled = await self._is_external_position_stop_loss_enabled()
        async with self.session_factory() as db:
            result = await db.execute(
                select(Position, Coin)
                .join(Coin, Position.coin_id == Coin.id)
                .where(Position.qty > 0)
            )
            rows = result.all()

        price_map = await self.upbit.get_tickers([coin.market for _position, coin in rows])
        portfolio_rows = []
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

        await self._store_portfolio_snapshot(portfolio_rows)

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

        # 미실현 손익 갱신 (항상)
        async with self.session_factory() as db:
            db_pos = await db.get(Position, position.id)
            if not db_pos or db_pos.qty <= 0:
                return None  # 이미 청산됨 (레이스 컨디션 방어)
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
                    db_pos.stop_loss is not None
                    and current_price <= db_pos.stop_loss
                )
                tp_triggered = (
                    db_pos.take_profit is not None
                    and current_price >= db_pos.take_profit
                )
                if sl_triggered:
                    trigger_reason = f"SL triggered: {current_price:.0f} <= {db_pos.stop_loss:.0f}"
                elif tp_triggered:
                    trigger_reason = f"TP triggered: {current_price:.0f} >= {db_pos.take_profit:.0f}"

            db_pos.unrealized_pnl = unrealized_pnl
            await db.commit()
            position.stop_loss = db_pos.stop_loss
            position.take_profit = db_pos.take_profit

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

        return {
            "coinId": position.coin_id,
            "market": coin.market,
            "qty": position.qty,
            "currentPrice": current_price,
            "marketValue": current_price * position.qty,
            "unrealizedPnl": unrealized_pnl,
        }

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

    async def _store_portfolio_snapshot(self, portfolio_rows: list[dict], balances: list[dict] | None = None):
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

            price_map = await self.upbit.get_tickers([coin.market for position, coin in rows if position.qty > 0])
            for position, coin in rows:
                current_price = price_map.get(coin.market)
                if current_price and current_price > 0:
                    portfolio_rows.append({
                        "coinId": position.coin_id,
                        "market": coin.market,
                        "qty": position.qty,
                        "currentPrice": current_price,
                        "marketValue": current_price * position.qty,
                        "unrealizedPnl": (current_price - position.avg_entry_price) * position.qty,
                    })

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
            await self._redis.rpush(PORTFOLIO_EQUITY_CURVE_KEY, payload)
            await self._redis.ltrim(PORTFOLIO_EQUITY_CURVE_KEY, -EQUITY_CURVE_MAX_POINTS, -1)
            await self._redis.set(PORTFOLIO_LATEST_SNAPSHOT_KEY, payload)
            await self._redis.publish("upbit:position_update", json.dumps({
                "type": "portfolio_snapshot",
                **snapshot,
            }))
        except Exception as e:
            logger.warning("Portfolio snapshot store failed: %s", e)

    # ── 공통 헬퍼 ──────────────────────────────────────────

    @staticmethod
    async def _update_signal_status(db, signal: Signal, status: str, reason: str | None):
        db_signal = await db.get(Signal, signal.id)
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

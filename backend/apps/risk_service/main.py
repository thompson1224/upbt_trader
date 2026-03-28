"""Risk service entry point - 독립적인 마이크로서비스로 위험 관리."""

import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from math import isclose
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis
from sqlalchemy import select

from libs.config import get_settings
from libs.db.session import get_session_factory
from libs.db.models import Fill, Order, Coin, Position, RuntimeState
from libs.upbit.rest_client import UpbitRestClient
from apps.risk_service.guards.pre_trade_guard import (
    PreTradeRiskGuard,
    PositionSizer,
    AccountState,
)
from apps.risk_service.account_tracker import AccountStateTracker
from apps.risk_service.portfolio_monitor import PortfolioRiskMonitor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
METRICS_PUBLISH_INTERVAL_SEC = 30
RISK_ALERT_CHANNEL = "upbit:risk_alert"
TRADE_EVENT_SUBSCRIBE_CHANNEL = "upbit:trade_event"
RISK_REQUEST_CHANNEL = "upbit:risk:request"
RISK_RESPONSE_CHANNEL = "upbit:risk:response"
DAILY_PNL_KEY_PREFIX = "risk:daily_pnl:"
RISK_STATUS_KEY = "risk:status"
RISK_METRICS_KEY = "risk:metrics"
UPBIT_FEE_RATE = 0.0005


def _risk_metric_date(now: datetime | None = None) -> str:
    kst = ZoneInfo("Asia/Seoul")
    ts = now.astimezone(kst) if now else datetime.now(tz=kst)
    return ts.strftime("%Y%m%d")


def _current_kst_day_start_utc(now: datetime | None = None) -> datetime:
    kst = ZoneInfo("Asia/Seoul")
    current = now.astimezone(kst) if now else datetime.now(tz=kst)
    return current.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(
        timezone.utc
    )


def _build_closed_trades_for_risk(fill_rows: list[dict]) -> list[dict]:
    """Fill 레코드 목록에서 완료된 트레이드(매도 기반)만 추출."""
    open_lots: dict[str, list[dict]] = defaultdict(list)
    trades: list[dict] = []

    for row in fill_rows:
        market = row["market"]
        side = row["side"]
        volume = row["volume"]
        price = row["price"]
        fee = row["fee"]
        filled_at = row["filled_at"]

        if side == "bid":
            open_lots[market].append(
                {
                    "remaining_qty": volume,
                    "remaining_funds": price * volume,
                    "remaining_fee": fee,
                    "entry_ts": filled_at,
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
            lot_qty = lot["remaining_qty"]
            if lot_qty <= 1e-9 or isclose(lot_qty, 0.0, abs_tol=1e-9):
                lots.pop(0)
                continue

            matched_qty = min(remaining_exit_qty, lot_qty)
            matched_ratio = matched_qty / max(lot_qty, 1e-12)
            entry_funds = lot["remaining_funds"] * matched_ratio
            entry_fee = lot["remaining_fee"] * matched_ratio
            exit_funds = price * matched_qty
            exit_fee = fee * (matched_qty / max(volume, 1e-12))
            gross_pnl = exit_funds - entry_funds
            net_pnl = gross_pnl - entry_fee - exit_fee

            trades.append(
                {
                    "exit_ts": filled_at,
                    "net_pnl": net_pnl,
                    "market": market,
                }
            )

            lot["remaining_qty"] -= matched_qty
            lot["remaining_funds"] -= entry_funds
            lot["remaining_fee"] -= entry_fee
            remaining_exit_qty -= matched_qty

            if lot["remaining_qty"] <= 1e-9 or isclose(
                lot["remaining_qty"], 0.0, abs_tol=1e-9
            ):
                lots.pop(0)

    trades.sort(key=lambda trade: trade["exit_ts"])
    return trades


class RiskService:
    def __init__(self):
        self.settings = get_settings()
        self.session_factory = get_session_factory()
        self.upbit = UpbitRestClient()
        self.risk_guard = PreTradeRiskGuard()
        self.position_sizer = PositionSizer()
        self.account_tracker = AccountStateTracker()
        self.portfolio_monitor = PortfolioRiskMonitor()
        self._redis: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._shutdown = False

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(REDIS_URL)
        return self._redis

    async def _ensure_redis_connection(self) -> bool:
        try:
            r = await self._get_redis()
            await r.ping()
            return True
        except Exception as e:
            logger.warning("Redis connection failed: %s", e)
            self._redis = None
            return False

    async def run(self):
        logger.info("Risk service started.")
        if not await self._ensure_redis_connection():
            logger.error(
                "Cannot connect to Redis. Risk service will not function properly."
            )
        await self._restore_state_from_redis()
        await asyncio.gather(
            self._trade_event_subscriber(),
            self._risk_request_handler(),
            self._metrics_publisher_loop(),
            self._portfolio_monitor_loop(),
            self._state_persistence_loop(),
        )

    async def _restore_state_from_redis(self):
        """Redis에서 마지막 상태를 복원."""
        try:
            r = await self._get_redis()
            daily_key = f"{DAILY_PNL_KEY_PREFIX}{_risk_metric_date()}"
            daily_raw = await r.get(daily_key)
            streak_raw = await r.get("risk:loss_streak")
            streak_date_raw = await r.get("risk:loss_streak:date")

            if daily_raw:
                self.account_tracker.daily_pnl = float(daily_raw.decode())
            if streak_raw:
                self.account_tracker.consecutive_losses = int(streak_raw.decode())
            if streak_date_raw:
                self.account_tracker.loss_streak_date = streak_date_raw.decode()

            current_date = _risk_metric_date()
            if self.account_tracker.loss_streak_date != current_date:
                self.account_tracker.consecutive_losses = 0
                self.account_tracker.loss_streak_date = current_date
                logger.info("Loss streak reset for new day")

            logger.info(
                "Restored state: daily_pnl=%.2f, consecutive_losses=%d",
                self.account_tracker.daily_pnl,
                self.account_tracker.consecutive_losses,
            )
        except Exception as e:
            logger.warning("Failed to restore state from Redis: %s", e)

    async def _trade_event_subscriber(self):
        """Redis pub/sub을 통해 trade event 수신."""
        while not self._shutdown:
            try:
                r = await self._get_redis()
                pubsub = r.pubsub()
                await pubsub.subscribe(TRADE_EVENT_SUBSCRIBE_CHANNEL)
                logger.info("Subscribed to %s", TRADE_EVENT_SUBSCRIBE_CHANNEL)

                async for message in pubsub.listen():
                    if self._shutdown:
                        break
                    if message["type"] != "message":
                        continue
                    try:
                        data = json.loads(message["data"])
                        await self._handle_trade_event(data)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Invalid JSON in trade event: %s", message["data"]
                        )
                    except Exception as e:
                        logger.error("Trade event handling error: %s", e)

            except Exception as e:
                logger.warning("Trade event subscriber error: %s", e)
                await asyncio.sleep(5)

    async def _handle_trade_event(self, data: dict):
        """Trade event 처리."""
        event_type = data.get("type", "")
        market = data.get("market", "")

        if event_type in ("order_filled", "sl_triggered", "tp_triggered"):
            await self._process_fill_event(data)
        elif event_type == "order_placed":
            logger.debug("Order placed: %s %s", market, data.get("side", ""))
        elif event_type == "risk_rejected":
            logger.info(
                "Signal rejected by risk guard: %s - %s", market, data.get("reason", "")
            )

    async def _risk_request_handler(self):
        """위험 평가 RPC 요청 처리 - execution_serviceからの 요청을 수신하여 평가 후 응답."""
        while not self._shutdown:
            try:
                r = await self._get_redis()
                pubsub = r.pubsub()
                await pubsub.subscribe(RISK_REQUEST_CHANNEL)
                logger.info("Subscribed to %s", RISK_REQUEST_CHANNEL)

                async for message in pubsub.listen():
                    if self._shutdown:
                        break
                    if message["type"] != "message":
                        continue
                    try:
                        request_data = json.loads(message["data"])
                        response = await self._evaluate_risk_request(request_data)
                        await r.publish(RISK_RESPONSE_CHANNEL, json.dumps(response))
                    except json.JSONDecodeError:
                        logger.warning(
                            "Invalid JSON in risk request: %s", message["data"]
                        )
                    except Exception as e:
                        logger.error("Risk request handling error: %s", e)

            except Exception as e:
                logger.warning("Risk request handler error: %s", e)
                await asyncio.sleep(5)

    async def _evaluate_risk_request(self, request: dict) -> dict:
        """위험 평가 요청 처리 및 응답 생성."""
        request_id = request.get("request_id", "")
        side = request.get("side", "buy")
        market = request.get("market", "")
        suggested_qty = request.get("suggested_qty", 0.0)
        entry_price = request.get("entry_price", 0.0)
        stop_loss = request.get("stop_loss")
        account_data = request.get("account", {})

        account = AccountState(
            total_equity=account_data.get("total_equity", 0.0),
            available_krw=account_data.get("available_krw", 0.0),
            daily_pnl=account_data.get("daily_pnl", 0.0),
            consecutive_losses=account_data.get("consecutive_losses", 0),
            open_positions_count=account_data.get("open_positions_count", 0),
            market_warning=account_data.get("market_warning", False),
        )

        decision = self.risk_guard.evaluate(
            side=side,
            market=market,
            suggested_qty=suggested_qty,
            entry_price=entry_price,
            stop_loss=stop_loss,
            account=account,
        )

        return {
            "request_id": request_id,
            "approved": decision.approved,
            "reason": decision.reason,
            "adjusted_qty": decision.adjusted_qty,
        }

    async def _process_fill_event(self, data: dict):
        """체결 이벤트에서 P&L 추적."""
        try:
            async with self.session_factory() as db:
                result = await db.execute(
                    select(Fill, Order, Coin.market)
                    .join(Order, Fill.order_id == Order.id)
                    .join(Coin, Order.coin_id == Coin.id)
                    .where(Order.side == "ask")
                    .order_by(Fill.filled_at.desc())
                    .limit(100)
                )
                rows = result.all()

            fill_rows = [
                {
                    "market": market,
                    "side": order.side,
                    "volume": fill.volume,
                    "price": fill.price,
                    "fee": fill.fee,
                    "filled_at": fill.filled_at,
                }
                for fill, order, market in rows
            ]

            trades = _build_closed_trades_for_risk(fill_rows)
            if trades:
                latest_trade = trades[-1]
                pnl = latest_trade.get("net_pnl", 0.0)
                if pnl != 0:
                    self.account_tracker.record_trade(pnl)
                    logger.info(
                        "Trade recorded: market=%s pnl=%.2f total_pnl=%.2f streak=%d",
                        latest_trade.get("market", ""),
                        pnl,
                        self.account_tracker.daily_pnl,
                        self.account_tracker.consecutive_losses,
                    )
        except Exception as e:
            logger.error("Failed to process fill event: %s", e)

    async def _metrics_publisher_loop(self):
        """주기적으로 risk metrics를 Redis에 발행."""
        while not self._shutdown:
            try:
                await asyncio.sleep(METRICS_PUBLISH_INTERVAL_SEC)
                await self._publish_risk_metrics()
            except Exception as e:
                logger.error("Metrics publisher error: %s", e)

    async def _publish_risk_metrics(self):
        """현재 risk metrics를 Redis에 저장."""
        try:
            r = await self._get_redis()
            daily_key = f"{DAILY_PNL_KEY_PREFIX}{_risk_metric_date()}"

            metrics = {
                "daily_pnl": self.account_tracker.daily_pnl,
                "consecutive_losses": self.account_tracker.consecutive_losses,
                "open_positions": self.account_tracker.open_positions_count,
                "total_equity": self.account_tracker.total_equity,
                "available_krw": self.account_tracker.available_krw,
                "ts": datetime.now(tz=timezone.utc).isoformat(),
            }

            await r.set(daily_key, self.account_tracker.daily_pnl)
            await r.expire(daily_key, 60 * 60 * 48)
            await r.set("risk:loss_streak", self.account_tracker.consecutive_losses)
            await r.set("risk:loss_streak:date", self.account_tracker.loss_streak_date)
            await r.set(RISK_METRICS_KEY, json.dumps(metrics))

            daily_loss_pct = abs(self.account_tracker.daily_pnl) / max(
                self.account_tracker.total_equity, 1
            )
            status = "healthy"
            if daily_loss_pct >= self.settings.risk_max_daily_loss_pct * 0.8:
                status = "warning"
            if daily_loss_pct >= self.settings.risk_max_daily_loss_pct:
                status = "critical"
            if self.account_tracker.consecutive_losses >= 5:
                status = "critical"
            await r.set(RISK_STATUS_KEY, status)

            logger.debug(
                "Published metrics: daily_pnl=%.2f streak=%d status=%s",
                self.account_tracker.daily_pnl,
                self.account_tracker.consecutive_losses,
                status,
            )
        except Exception as e:
            logger.error("Failed to publish risk metrics: %s", e)

    async def _portfolio_monitor_loop(self):
        """포트폴리오 위험 모니터링."""
        while not self._shutdown:
            try:
                await asyncio.sleep(60)
                await self._check_portfolio_risk()
            except Exception as e:
                logger.error("Portfolio monitor error: %s", e)

    async def _check_portfolio_risk(self):
        """포트폴리오 위험 상태 점검 및 알림."""
        try:
            r = await self._get_redis()
            balances = await self.upbit.get_balances()
            await self.account_tracker.sync_from_exchange(balances)

            alerts = await self.portfolio_monitor.evaluate(
                account_tracker=self.account_tracker,
                settings=self.settings,
            )

            for alert in alerts:
                await r.publish(RISK_ALERT_CHANNEL, json.dumps(alert))
                logger.warning(
                    "Risk alert: %s - %s (value=%.4f threshold=%.4f)",
                    alert["type"],
                    alert.get("market", "portfolio"),
                    alert.get("value", 0),
                    alert.get("threshold", 0),
                )
        except Exception as e:
            logger.error("Failed to check portfolio risk: %s", e)

    async def _state_persistence_loop(self):
        """주기적으로 DB에 상태 저장."""
        while not self._shutdown:
            try:
                await asyncio.sleep(300)
                await self._persist_state_to_db()
            except Exception as e:
                logger.error("State persistence error: %s", e)

    async def _persist_state_to_db(self):
        """현재 상태를 DB에 저장."""
        try:
            async with self.session_factory() as db:
                daily_key = f"risk.daily_pnl.{_risk_metric_date()}"
                daily_state = await db.get(RuntimeState, daily_key)
                if daily_state is None:
                    db.add(
                        RuntimeState(
                            key=daily_key,
                            value=str(self.account_tracker.daily_pnl),
                        )
                    )
                else:
                    daily_state.value = str(self.account_tracker.daily_pnl)

                streak_key = "risk.loss_streak"
                streak_state = await db.get(RuntimeState, streak_key)
                if streak_state is None:
                    db.add(
                        RuntimeState(
                            key=streak_key,
                            value=str(self.account_tracker.consecutive_losses),
                        )
                    )
                else:
                    streak_state.value = str(self.account_tracker.consecutive_losses)

                await db.commit()
                logger.debug("State persisted to DB")
        except Exception as e:
            logger.error("Failed to persist state to DB: %s", e)

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Risk service shutting down...")
        self._shutdown = True
        await self._persist_state_to_db()
        if self._redis:
            await self._redis.close()


async def main():
    service = RiskService()
    try:
        await service.run()
    except KeyboardInterrupt:
        await service.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

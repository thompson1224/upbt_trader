from __future__ import annotations
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import isclose
from typing import Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from libs.audit import record_audit_event
from libs.config import get_settings
from libs.db.session import get_db
from libs.db.models import AuditEvent, Position, Coin, RuntimeState, Fill, Order, Signal
from libs.signal_reason import humanize_signal_reason

router = APIRouter()
PORTFOLIO_EQUITY_CURVE_KEY = "portfolio:equity_curve"
PORTFOLIO_LATEST_SNAPSHOT_KEY = "portfolio:latest_snapshot"
PORTFOLIO_PERFORMANCE_CACHE_KEY_PREFIX = "portfolio:performance:v1:"
PORTFOLIO_PERFORMANCE_CACHE_TTL_SECONDS = 15
POSITION_SOURCE_STRATEGY = "strategy"
POSITION_SOURCE_EXTERNAL = "external"
POSITION_SOURCE_OVERRIDE_KEY_PREFIX = "position.management."
KST = timezone(timedelta(hours=9))
HOLD_STALE_MINUTES_REDIS_KEY = "settings:hold_stale_minutes"
EXCLUDED_MARKETS_REDIS_KEY = "settings:excluded_markets"
RISK_LOSS_STREAK_REDIS_KEY = "risk:loss_streak"
DAILY_REPORT_RUNTIME_STATE_PREFIX = "daily.report."


class PositionAutoTradeRequest(BaseModel):
    enabled: bool


def _get_redis():
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    return aioredis.from_url(redis_url)


def _position_management_key(coin_id: int) -> str:
    return f"{POSITION_SOURCE_OVERRIDE_KEY_PREFIX}{coin_id}"


async def _get_hold_stale_minutes() -> int:
    r = _get_redis()
    try:
        val = await r.get(HOLD_STALE_MINUTES_REDIS_KEY)
    finally:
        await r.aclose()
    if val is not None:
        return int(val.decode())
    return int(get_settings().risk_hold_stale_minutes)


def _performance_cache_key(limit: int, days: Optional[int], market: Optional[str]) -> str:
    range_key = "all" if days is None else f"{days}d"
    market_key = (market or "all").upper().replace(":", "_")
    return f"{PORTFOLIO_PERFORMANCE_CACHE_KEY_PREFIX}{limit}:{range_key}:{market_key}"


def _current_kst_date_key(now: datetime | None = None) -> str:
    current = now.astimezone(KST) if now is not None else datetime.now(KST)
    return current.strftime("%Y%m%d")


def _current_kst_day_start_utc(now: datetime | None = None) -> datetime:
    current = now.astimezone(KST) if now is not None else datetime.now(KST)
    day_start_kst = current.replace(hour=0, minute=0, second=0, microsecond=0)
    return day_start_kst.astimezone(timezone.utc)


def _kst_date_range_utc(date_key: str) -> tuple[datetime, datetime]:
    day_start_kst = datetime.strptime(date_key, "%Y%m%d").replace(tzinfo=KST)
    day_end_kst = day_start_kst + timedelta(days=1)
    return day_start_kst.astimezone(timezone.utc), day_end_kst.astimezone(timezone.utc)


def _parse_excluded_market_state(raw: str | bytes | None) -> dict:
    if raw is None:
        return {"markets": [], "items": []}
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"markets": [], "items": []}
    if isinstance(parsed, list):
        markets = [str(item).upper() for item in parsed]
        return {"markets": markets, "items": [{"market": market, "reason": "", "updated_at": ""} for market in markets]}
    items = parsed.get("items") if isinstance(parsed, dict) else None
    normalized_items = []
    for item in items or []:
        market = str(item.get("market", "")).upper()
        if not market:
            continue
        normalized_items.append(
            {
                "market": market,
                "reason": str(item.get("reason", "") or ""),
                "updated_at": str(item.get("updated_at", "") or ""),
            }
        )
    return {
        "markets": [item["market"] for item in normalized_items],
        "items": normalized_items,
    }


def _safe_load_json(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _group_audit_reason_counts(audit_rows: list[AuditEvent], *, event_type: str) -> list[dict]:
    counts: dict[str, int] = defaultdict(int)
    for row in audit_rows:
        if row.event_type != event_type:
            continue
        payload = _safe_load_json(row.payload_json)
        reason = None
        if payload is not None:
            reason = str(payload.get("reason", "") or "").strip()
        if not reason:
            reason = row.message.strip() if row.message else "unknown"
        counts[reason] += 1

    rows = [{"reason": reason, "count": count} for reason, count in counts.items()]
    rows.sort(key=lambda row: (-row["count"], row["reason"]))
    return rows


def _daily_report_runtime_state_key(date_key: str) -> str:
    return f"{DAILY_REPORT_RUNTIME_STATE_PREFIX}{date_key}"


async def _persist_daily_report_snapshot(db: AsyncSession, date_key: str, payload: dict) -> None:
    key = _daily_report_runtime_state_key(date_key)
    state = await db.get(RuntimeState, key)
    serialized = json.dumps(payload)
    if state is None:
        db.add(RuntimeState(key=key, value=serialized))
    else:
        state.value = serialized
    await db.commit()


async def _load_runtime_risk_daily_pnl_for_date(db: AsyncSession, date_key: str) -> float:
    state = await db.get(RuntimeState, f"risk.daily_pnl.{date_key}")
    if state is None:
        return 0.0
    try:
        return float(state.value)
    except (TypeError, ValueError):
        return 0.0


async def _persist_runtime_risk_daily_pnl_for_date(
    db: AsyncSession,
    *,
    date_key: str,
    value: float,
) -> None:
    key = f"risk.daily_pnl.{date_key}"
    state = await db.get(RuntimeState, key)
    serialized = str(value)
    if state is None:
        db.add(RuntimeState(key=key, value=serialized))
    else:
        state.value = serialized
    await db.commit()


async def _build_daily_report_analytics(
    db: AsyncSession,
    *,
    start_utc: datetime,
    end_utc: datetime | None,
) -> dict:
    fill_stmt = (
        select(Fill, Order, Coin.market, Signal)
        .join(Order, Fill.order_id == Order.id)
        .join(Coin, Order.coin_id == Coin.id)
        .outerjoin(Signal, Order.signal_id == Signal.id)
        .where(Fill.filled_at >= start_utc)
        .order_by(Fill.filled_at.asc(), Fill.id.asc())
    )
    if end_utc is not None:
        fill_stmt = fill_stmt.where(Fill.filled_at < end_utc)
    fill_rows_result = await db.execute(fill_stmt)
    fill_rows = [
        {
            "market": market,
            "side": order.side,
            "price": fill.price,
            "volume": fill.volume,
            "fee": fill.fee,
            "filledAt": fill.filled_at,
            "signal": signal,
            "orderReason": order.rejected_reason,
            "strategyId": signal.strategy_id if signal else None,
            "taScore": signal.ta_score if signal else None,
            "sentimentScore": signal.sentiment_score if signal else None,
            "finalScore": signal.final_score if signal else None,
            "confidence": signal.confidence if signal else None,
        }
        for fill, order, market, signal in fill_rows_result.all()
    ]
    trades = _build_closed_trades(fill_rows)

    audit_stmt = (
        select(AuditEvent)
        .where(AuditEvent.created_at >= start_utc)
        .order_by(AuditEvent.created_at.desc())
    )
    if end_utc is not None:
        audit_stmt = audit_stmt.where(AuditEvent.created_at < end_utc)
    audit_rows = (await db.execute(audit_stmt)).scalars().all()

    risk_rejected_count = sum(1 for row in audit_rows if row.event_type == "risk_rejected")
    order_failed_count = sum(1 for row in audit_rows if row.event_type == "order_failed")
    excluded_ops_count = sum(
        1
        for row in audit_rows
        if row.event_type in {
            "excluded_market_added",
            "excluded_market_restored",
            "excluded_market_reason_updated",
        }
    )

    return {
        "trades": trades,
        "riskRejectedCount": risk_rejected_count,
        "orderFailedCount": order_failed_count,
        "excludedOpsCount": excluded_ops_count,
        "recentAuditCounts": {
            "riskRejected": risk_rejected_count,
            "orderFailed": order_failed_count,
            "excludedOps": excluded_ops_count,
        },
        "byExitReason": _group_performance(trades, "exitReason"),
        "analysis": {
            "byFinalScoreBand": _group_score_band_performance(trades),
            "byHourBlock": _group_hour_block_performance(trades),
            "weakMarkets": sorted(
                _group_performance(trades, "market"),
                key=lambda row: row["netPnl"],
            )[:3],
            "riskRejectedReasons": _group_audit_reason_counts(
                audit_rows,
                event_type="risk_rejected",
            )[:5],
        },
    }


async def _backfill_daily_report_payload(
    db: AsyncSession,
    *,
    date_key: str,
    payload: dict,
) -> dict:
    start_utc, end_utc = _kst_date_range_utc(date_key)
    analytics = await _build_daily_report_analytics(db, start_utc=start_utc, end_utc=end_utc)
    trades = analytics["trades"]
    recomputed_daily_pnl = sum(trade["netPnl"] for trade in trades)
    await _persist_runtime_risk_daily_pnl_for_date(db, date_key=date_key, value=recomputed_daily_pnl)

    summary = dict(payload.get("summary") or {})
    summary.update(
        {
            "dailyPnl": recomputed_daily_pnl,
            "runtimeRiskDailyPnl": recomputed_daily_pnl,
            "closedTrades": len(trades),
            "wins": sum(1 for trade in trades if trade["netPnl"] > 0),
            "losses": sum(1 for trade in trades if trade["netPnl"] < 0),
            "netPnl": recomputed_daily_pnl,
            "riskRejectedCount": analytics["riskRejectedCount"],
            "orderFailedCount": analytics["orderFailedCount"],
            "excludedOpsCount": analytics["excludedOpsCount"],
        }
    )

    updated_payload = dict(payload)
    updated_payload["date"] = date_key
    updated_payload["summary"] = summary
    updated_payload["byExitReason"] = analytics["byExitReason"]
    updated_payload["analysis"] = analytics["analysis"]
    updated_payload["recentAuditCounts"] = analytics["recentAuditCounts"]
    return updated_payload


def _default_protection_levels(
    entry_price: float,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> tuple[float | None, float | None]:
    if entry_price <= 0:
        return None, None
    safe_stop_loss_pct = min(max(stop_loss_pct, 0.0), 0.99)
    safe_take_profit_pct = max(take_profit_pct, 0.0)
    return (
        entry_price * (1 - safe_stop_loss_pct),
        entry_price * (1 + safe_take_profit_pct),
    )


def _infer_exit_reason(signal: Signal | None, order_reason: str | None) -> str:
    normalized_reason = (order_reason or "").lower()
    if normalized_reason.startswith("sl triggered"):
        return "stop_loss"
    if normalized_reason.startswith("tp triggered"):
        return "take_profit"
    if signal is None:
        return "protection"
    if signal.strategy_id == "manual-test":
        return "manual"
    if signal.side == "sell":
        return "sell_signal"
    return "system"


def _build_closed_trades(fill_rows: list[dict]) -> list[dict]:
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
                    "strategyId": row.get("strategyId"),
                    "taScore": row.get("taScore"),
                    "sentimentScore": row.get("sentimentScore"),
                    "finalScore": row.get("finalScore"),
                    "confidence": row.get("confidence"),
                }
            )
            continue

        lots = open_lots.get(market)
        if not lots or volume <= 0:
            continue

        remaining_exit_qty = volume
        exit_reason = _infer_exit_reason(
            row.get("signal"),
            row.get("orderReason"),
        )

        while lots and remaining_exit_qty > 1e-9 and not isclose(remaining_exit_qty, 0.0, abs_tol=1e-9):
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
            trades.append(
                {
                    "market": market,
                    "entryTs": lot["entryTs"].isoformat(),
                    "exitTs": filled_at.isoformat(),
                    "entryPrice": entry_funds / max(matched_qty, 1e-12),
                    "exitPrice": exit_funds / max(matched_qty, 1e-12),
                    "qty": matched_qty,
                    "entryFee": entry_fee,
                    "exitFee": exit_fee,
                    "grossPnl": gross_pnl,
                    "netPnl": net_pnl,
                    "returnPct": (net_pnl / entry_funds) if entry_funds else 0.0,
                    "holdMinutes": max(
                        (filled_at - lot["entryTs"]).total_seconds() / 60.0,
                        0.0,
                    ),
                    "exitReason": exit_reason,
                    "strategyId": lot.get("strategyId"),
                    "taScore": lot.get("taScore"),
                    "sentimentScore": lot.get("sentimentScore"),
                    "finalScore": lot.get("finalScore"),
                    "confidence": lot.get("confidence"),
                }
            )
            lot["remainingQty"] -= matched_qty
            lot["remainingFunds"] -= entry_funds
            lot["remainingFee"] -= entry_fee
            remaining_exit_qty -= matched_qty

            if lot["remainingQty"] <= 1e-9 or isclose(lot["remainingQty"], 0.0, abs_tol=1e-9):
                lots.pop(0)

    trades.sort(key=lambda trade: trade["exitTs"], reverse=True)
    return trades


def _summarize_performance(trades: list[dict]) -> dict:
    total_trades = len(trades)
    wins = [trade for trade in trades if trade["netPnl"] > 0]
    losses = [trade for trade in trades if trade["netPnl"] < 0]
    gross_pnl = sum(trade["grossPnl"] for trade in trades)
    net_pnl = sum(trade["netPnl"] for trade in trades)
    total_win_pnl = sum(trade["netPnl"] for trade in wins)
    total_loss_pnl = sum(trade["netPnl"] for trade in losses)
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0

    for trade in reversed(trades):
        cumulative += trade["netPnl"]
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)

    return {
        "totalTrades": total_trades,
        "winRate": (len(wins) / total_trades) if total_trades else 0.0,
        "grossPnl": gross_pnl,
        "netPnl": net_pnl,
        "avgNetPnl": (net_pnl / total_trades) if total_trades else 0.0,
        "avgWin": (total_win_pnl / len(wins)) if wins else 0.0,
        "avgLoss": (total_loss_pnl / len(losses)) if losses else 0.0,
        "profitFactor": (total_win_pnl / abs(total_loss_pnl)) if losses else (float("inf") if wins else 0.0),
        "maxDrawdown": abs(max_drawdown),
        "bestTrade": max((trade["netPnl"] for trade in trades), default=0.0),
        "worstTrade": min((trade["netPnl"] for trade in trades), default=0.0),
    }


def _group_performance(trades: list[dict], key: str) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for trade in trades:
        grouped[str(trade.get(key) or "unknown")].append(trade)

    rows = []
    for group_key, items in grouped.items():
        total = len(items)
        net_pnl = sum(item["netPnl"] for item in items)
        wins = sum(1 for item in items if item["netPnl"] > 0)
        rows.append(
            {
                key: group_key,
                "trades": total,
                "winRate": (wins / total) if total else 0.0,
                "netPnl": net_pnl,
            }
        )

    rows.sort(key=lambda row: row["netPnl"], reverse=True)
    return rows


def _score_band_label(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value < 0.50:
        return "<0.50"
    if value < 0.60:
        return "0.50-0.59"
    if value < 0.70:
        return "0.60-0.69"
    if value < 0.80:
        return "0.70-0.79"
    return "0.80+"


def _group_score_band_performance(trades: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for trade in trades:
        grouped[_score_band_label(trade.get("finalScore"))].append(trade)

    def _sort_key(label: str) -> tuple[int, str]:
        order = {
            "<0.50": 0,
            "0.50-0.59": 1,
            "0.60-0.69": 2,
            "0.70-0.79": 3,
            "0.80+": 4,
            "unknown": 5,
        }
        return (order.get(label, 99), label)

    rows = []
    for score_band, items in grouped.items():
        total = len(items)
        wins = sum(1 for item in items if item["netPnl"] > 0)
        rows.append(
            {
                "scoreBand": score_band,
                "trades": total,
                "winRate": (wins / total) if total else 0.0,
                "netPnl": sum(item["netPnl"] for item in items),
            }
        )

    rows.sort(key=lambda row: _sort_key(row["scoreBand"]))
    return rows


def _sentiment_band_label(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value < -0.25:
        return "<-0.25"
    if value < 0.0:
        return "-0.25~-0.01"
    if value < 0.25:
        return "0.00-0.24"
    if value < 0.50:
        return "0.25-0.49"
    return "0.50+"


def _group_sentiment_band_performance(trades: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for trade in trades:
        grouped[_sentiment_band_label(trade.get("sentimentScore"))].append(trade)

    def _sort_key(label: str) -> tuple[int, str]:
        order = {
            "<-0.25": 0,
            "-0.25~-0.01": 1,
            "0.00-0.24": 2,
            "0.25-0.49": 3,
            "0.50+": 4,
            "unknown": 5,
        }
        return (order.get(label, 99), label)

    rows = []
    for sentiment_band, items in grouped.items():
        total = len(items)
        wins = sum(1 for item in items if item["netPnl"] > 0)
        rows.append(
            {
                "sentimentBand": sentiment_band,
                "trades": total,
                "winRate": (wins / total) if total else 0.0,
                "netPnl": sum(item["netPnl"] for item in items),
            }
        )

    rows.sort(key=lambda row: _sort_key(row["sentimentBand"]))
    return rows


def _hour_block_label(exit_ts: str) -> str:
    hour = datetime.fromisoformat(exit_ts).astimezone(KST).hour
    if hour < 4:
        return "00-04"
    if hour < 8:
        return "04-08"
    if hour < 12:
        return "08-12"
    if hour < 16:
        return "12-16"
    if hour < 20:
        return "16-20"
    return "20-24"


def _group_hour_block_performance(trades: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for trade in trades:
        grouped[_hour_block_label(trade["exitTs"])].append(trade)

    order = {
        "00-04": 0,
        "04-08": 1,
        "08-12": 2,
        "12-16": 3,
        "16-20": 4,
        "20-24": 5,
    }

    rows = []
    for hour_block, items in grouped.items():
        total = len(items)
        wins = sum(1 for item in items if item["netPnl"] > 0)
        rows.append(
            {
                "hourBlock": hour_block,
                "trades": total,
                "winRate": (wins / total) if total else 0.0,
                "netPnl": sum(item["netPnl"] for item in items),
            }
        )

    rows.sort(key=lambda row: order.get(row["hourBlock"], 99))
    return rows


def _group_signal_transitions(signals: list[Signal]) -> list[dict]:
    grouped_by_coin: dict[int, list[Signal]] = defaultdict(list)
    for signal in signals:
        grouped_by_coin[signal.coin_id].append(signal)

    transition_counts: dict[str, int] = defaultdict(int)
    transition_gaps: dict[str, list[float]] = defaultdict(list)
    total_transitions = 0

    for coin_signals in grouped_by_coin.values():
        ordered = sorted(coin_signals, key=lambda signal: signal.ts)
        for previous, current in zip(ordered, ordered[1:]):
            label = f"{previous.side}->{current.side}"
            transition_counts[label] += 1
            transition_gaps[label].append(
                max((current.ts - previous.ts).total_seconds() / 60.0, 0.0)
            )
            total_transitions += 1

    rows = []
    for transition, count in transition_counts.items():
        gaps = transition_gaps[transition]
        rows.append(
            {
                "transition": transition,
                "count": count,
                "share": (count / total_transitions) if total_transitions else 0.0,
                "avgGapMinutes": (sum(gaps) / len(gaps)) if gaps else 0.0,
            }
        )

    rows.sort(key=lambda row: (-row["count"], row["transition"]))
    return rows


def _group_market_transition_quality(signal_rows: list[dict]) -> list[dict]:
    grouped_by_market: dict[str, list[dict]] = defaultdict(list)
    for row in signal_rows:
        grouped_by_market[row["market"]].append(row)

    rows = []
    for market, items in grouped_by_market.items():
        ordered = sorted(items, key=lambda item: item["ts"])
        transition_counts: dict[str, int] = defaultdict(int)
        total_transitions = 0

        for previous, current in zip(ordered, ordered[1:]):
            label = f"{previous['side']}->{current['side']}"
            transition_counts[label] += 1
            total_transitions += 1

        hold_origin_count = sum(
            count for label, count in transition_counts.items() if label.startswith("hold->")
        )
        hold_to_sell_count = transition_counts.get("hold->sell", 0)
        hold_to_hold_count = transition_counts.get("hold->hold", 0)
        hold_to_buy_count = transition_counts.get("hold->buy", 0)

        rows.append(
            {
                "market": market,
                "totalTransitions": total_transitions,
                "holdOriginCount": hold_origin_count,
                "holdToSellCount": hold_to_sell_count,
                "holdToHoldCount": hold_to_hold_count,
                "holdToBuyCount": hold_to_buy_count,
                "holdToSellRate": (hold_to_sell_count / hold_origin_count) if hold_origin_count else 0.0,
                "holdToHoldRate": (hold_to_hold_count / hold_origin_count) if hold_origin_count else 0.0,
            }
        )

    rows.sort(
        key=lambda row: (
            row["holdToSellRate"] if row["holdOriginCount"] else 1.0,
            -(row["holdToHoldRate"]),
            -(row["holdOriginCount"]),
            row["market"],
        )
    )
    return rows


def _get_market_transition_quality(
    signal_rows: list[dict],
    market: str,
) -> dict:
    rows = _group_market_transition_quality(signal_rows)
    for row in rows:
        if row["market"] == market:
            return row
    return {
        "market": market,
        "totalTransitions": 0,
        "holdOriginCount": 0,
        "holdToSellCount": 0,
        "holdToHoldCount": 0,
        "holdToBuyCount": 0,
        "holdToSellRate": 0.0,
        "holdToHoldRate": 0.0,
    }


def _serialize_signal(signal: Signal | None) -> dict | None:
    if signal is None:
        return None
    return {
        "id": signal.id,
        "strategy_id": signal.strategy_id,
        "ts": signal.ts.isoformat(),
        "side": signal.side,
        "status": signal.status,
        "final_score": signal.final_score,
        "confidence": signal.confidence,
        "rejection_reason": signal.rejection_reason,
        "display_reason": humanize_signal_reason(signal.rejection_reason),
    }


def _estimate_current_price(position: Position) -> float | None:
    if position.qty <= 0:
        return None
    return position.avg_entry_price + (position.unrealized_pnl / position.qty)


def _distance_to_threshold_pct(current_price: float | None, threshold: float | None, *, direction: str) -> float | None:
    if current_price is None or current_price <= 0 or threshold is None:
        return None
    if direction == "up":
        return ((threshold - current_price) / current_price) * 100
    return ((current_price - threshold) / current_price) * 100


def _describe_sell_wait_reason(
    position: Position,
    latest_signal: Signal | None,
    latest_sell_signal: Signal | None,
    current_price: float | None,
) -> tuple[str, str]:
    if position.source != POSITION_SOURCE_STRATEGY:
        return (
            "external_position",
            "외부 포지션이라 자동 매도 관리 대상이 아닙니다.",
        )
    if position.take_profit is not None and current_price is not None and current_price >= position.take_profit:
        return (
            "take_profit_reached_pending_sync",
            "현재가가 익절가에 도달했습니다. 주문 체결 또는 동기화 상태를 확인하세요.",
        )
    if position.stop_loss is not None and current_price is not None and current_price <= position.stop_loss:
        return (
            "stop_loss_reached_pending_sync",
            "현재가가 손절가에 도달했습니다. 주문 체결 또는 동기화 상태를 확인하세요.",
        )
    if latest_sell_signal is not None:
        if latest_sell_signal.status in {"new", "approved"}:
            return (
                "sell_signal_pending",
                "최근 매도 신호가 발생했고 주문 실행 대기 중입니다.",
            )
        if latest_sell_signal.status == "executed":
            return (
                "sell_signal_executed",
                "최근 매도 신호는 이미 실행 처리됐고 체결/동기화를 기다리는 상태일 수 있습니다.",
            )
        if latest_sell_signal.status == "rejected":
            reason = latest_sell_signal.rejection_reason or "사유 없음"
            return (
                "sell_signal_rejected",
                f"최근 매도 신호가 거절됐습니다: {reason}",
            )
        if latest_sell_signal.status == "expired":
            return (
                "sell_signal_expired",
                "최근 매도 신호가 만료돼 새 신호를 기다리는 중입니다.",
            )
    if latest_signal is None:
        return (
            "no_recent_signal",
            "최근 신호가 없어 현재 포지션 보호 규칙만 유지 중입니다.",
        )
    if latest_signal.side == "hold":
        return (
            "hold_signal",
            "최근 신호가 hold 라서 매도 조건이 아직 아닙니다.",
        )
    if latest_signal.side == "buy":
        return (
            "buy_signal",
            "최근 신호가 buy 라서 포지션 유지 중입니다.",
        )
    return (
        "sell_signal_unknown",
        "최근 매도 신호 상태를 확인하세요.",
    )


def _compute_hold_streak(
    signals: list[Signal],
    *,
    threshold_minutes: int,
) -> tuple[int, float | None, bool, str | None]:
    if not signals or signals[0].side != "hold":
        return 0, None, False, None

    streak_signals: list[Signal] = []
    for signal in signals:
        if signal.side != "hold":
            break
        streak_signals.append(signal)

    if not streak_signals:
        return 0, None, False, None

    oldest_hold = streak_signals[-1]
    duration_minutes = max(
        (datetime.now(tz=timezone.utc) - oldest_hold.ts).total_seconds() / 60.0,
        0.0,
    )
    is_stale = duration_minutes >= threshold_minutes
    warning = None
    if is_stale:
        warning = (
            f"최근 {len(streak_signals)}개 신호가 연속 hold 입니다. "
            f"약 {int(round(duration_minutes))}분째 관망 중입니다."
        )
    return len(streak_signals), duration_minutes, is_stale, warning


@router.get("/positions")
async def get_positions(db: AsyncSession = Depends(get_db)):
    hold_stale_minutes = await _get_hold_stale_minutes()
    stmt = select(Position, Coin.market, Coin.id).join(Coin)
    result = await db.execute(stmt)
    rows = result.all()
    active_rows = [(pos, market, coin_id) for pos, market, coin_id in rows if pos.qty > 0]
    if not active_rows:
        return []

    coin_ids = [coin_id for _pos, _market, coin_id in active_rows]
    signal_result = await db.execute(
        select(Signal)
        .where(Signal.coin_id.in_(coin_ids))
        .order_by(Signal.coin_id.asc(), Signal.ts.desc())
    )
    latest_signal_by_coin_id: dict[int, Signal] = {}
    latest_sell_signal_by_coin_id: dict[int, Signal] = {}
    signals_by_coin_id: dict[int, list[Signal]] = defaultdict(list)
    for signal in signal_result.scalars():
        signals_by_coin_id[signal.coin_id].append(signal)
        latest_signal_by_coin_id.setdefault(signal.coin_id, signal)
        if signal.side == "sell":
            latest_sell_signal_by_coin_id.setdefault(signal.coin_id, signal)

    payload = []
    for pos, market, coin_id in active_rows:
        latest_signal = latest_signal_by_coin_id.get(coin_id)
        latest_sell_signal = latest_sell_signal_by_coin_id.get(coin_id)
        coin_signals = signals_by_coin_id.get(coin_id, [])
        current_price = _estimate_current_price(pos)
        reason_code, reason_text = _describe_sell_wait_reason(
            pos,
            latest_signal,
            latest_sell_signal,
            current_price,
        )
        hold_count, hold_duration_minutes, hold_is_stale, hold_warning = _compute_hold_streak(
            coin_signals,
            threshold_minutes=hold_stale_minutes,
        )
        payload.append(
            {
                "id": pos.id,
                "market": market,
                "qty": pos.qty,
                "avg_entry_price": pos.avg_entry_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "realized_pnl": pos.realized_pnl,
                "source": pos.source,
                "stop_loss": pos.stop_loss,
                "take_profit": pos.take_profit,
                "current_price": current_price,
                "distance_to_stop_loss_pct": _distance_to_threshold_pct(current_price, pos.stop_loss, direction="down"),
                "distance_to_take_profit_pct": _distance_to_threshold_pct(current_price, pos.take_profit, direction="up"),
                "auto_trade_managed": pos.source == POSITION_SOURCE_STRATEGY,
                "latest_signal": _serialize_signal(latest_signal),
                "latest_sell_signal": _serialize_signal(latest_sell_signal),
                "sell_wait_reason_code": reason_code,
                "sell_wait_reason": reason_text,
                "consecutive_hold_count": hold_count,
                "hold_duration_minutes": hold_duration_minutes,
                "hold_stale": hold_is_stale,
                "hold_warning": hold_warning,
                "hold_stale_threshold_minutes": hold_stale_minutes,
            }
        )
    return payload


@router.patch("/positions/{market}/auto-trade")
async def set_position_auto_trade(
    market: str,
    req: PositionAutoTradeRequest,
    db: AsyncSession = Depends(get_db),
):
    normalized_market = market.upper()
    coin_result = await db.execute(select(Coin).where(Coin.market == normalized_market))
    coin = coin_result.scalar_one_or_none()
    if coin is None:
        raise HTTPException(status_code=404, detail="Market not found")

    position_result = await db.execute(select(Position).where(Position.coin_id == coin.id))
    position = position_result.scalar_one_or_none()
    if position is None or position.qty <= 0:
        raise HTTPException(status_code=404, detail="Open position not found")

    override_key = _position_management_key(coin.id)
    runtime_state = await db.get(RuntimeState, override_key)
    target_source = POSITION_SOURCE_STRATEGY if req.enabled else POSITION_SOURCE_EXTERNAL

    if runtime_state is None:
        db.add(RuntimeState(key=override_key, value=target_source))
    else:
        runtime_state.value = target_source

    position.source = target_source
    if req.enabled:
        settings = get_settings()
        stop_loss, take_profit = _default_protection_levels(
            position.avg_entry_price,
            settings.risk_default_stop_loss_pct,
            settings.risk_default_take_profit_pct,
        )
        position.stop_loss = stop_loss
        position.take_profit = take_profit
    else:
        position.stop_loss = None
        position.take_profit = None

    await db.commit()
    await db.refresh(position)

    await record_audit_event(
        event_type="position_auto_trade_toggled",
        source="portfolio",
        market=normalized_market,
        message=f"Position {normalized_market} {'included in' if req.enabled else 'excluded from'} auto-trade",
        payload={
            "enabled": req.enabled,
            "coin_id": coin.id,
            "position_id": position.id,
        },
    )

    return {
        "id": position.id,
        "market": normalized_market,
        "qty": position.qty,
        "avg_entry_price": position.avg_entry_price,
        "source": position.source,
        "stop_loss": position.stop_loss,
        "take_profit": position.take_profit,
        "auto_trade_managed": position.source == POSITION_SOURCE_STRATEGY,
    }


@router.get("/portfolio/equity-curve")
async def get_equity_curve(
    limit: int = Query(100, ge=1, le=500),
    days: Optional[int] = Query(None, ge=1, le=365),
):
    if not isinstance(limit, int):
        limit = 100
    if not isinstance(days, int):
        days = None
    r = _get_redis()
    try:
        items = await r.lrange(PORTFOLIO_EQUITY_CURVE_KEY, -limit, -1)
        latest = await r.get(PORTFOLIO_LATEST_SNAPSHOT_KEY)
    finally:
        await r.aclose()

    data = [json.loads(item) for item in items]
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        data = [
            point for point in data
            if datetime.fromisoformat(point["ts"]) >= cutoff
        ]
    latest_data = json.loads(latest) if latest else (data[-1] if data else None)
    return {"data": data, "latest": latest_data}


@router.get("/portfolio/performance")
async def get_portfolio_performance(
    limit: int = Query(100, ge=1, le=1000),
    days: Optional[int] = Query(None, ge=1, le=365),
    market: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if not isinstance(limit, int):
        limit = 100
    if not isinstance(days, int):
        days = None
    normalized_market = market.upper() if isinstance(market, str) and market.strip() else None
    cache_key = _performance_cache_key(limit, days, normalized_market)
    cached_payload = None
    redis_client = None
    try:
        redis_client = _get_redis()
        cached_payload = await redis_client.get(cache_key)
    except Exception:
        cached_payload = None
    finally:
        if redis_client is not None:
            await redis_client.aclose()

    if cached_payload:
        if isinstance(cached_payload, bytes):
            cached_payload = cached_payload.decode()
        return json.loads(cached_payload)

    stmt = (
        select(Fill, Order, Coin.market, Signal)
        .join(Order, Fill.order_id == Order.id)
        .join(Coin, Order.coin_id == Coin.id)
        .outerjoin(Signal, Order.signal_id == Signal.id)
        .order_by(Fill.filled_at.asc(), Fill.id.asc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    fill_rows = [
        {
            "market": market,
            "side": order.side,
            "price": fill.price,
            "volume": fill.volume,
            "fee": fill.fee,
            "filledAt": fill.filled_at,
            "signal": signal,
            "orderReason": order.rejected_reason,
            "strategyId": signal.strategy_id if signal else None,
            "taScore": signal.ta_score if signal else None,
            "sentimentScore": signal.sentiment_score if signal else None,
            "finalScore": signal.final_score if signal else None,
            "confidence": signal.confidence if signal else None,
        }
        for fill, order, market, signal in rows
    ]

    signal_stmt = (
        select(Signal, Coin.market)
        .join(Coin, Signal.coin_id == Coin.id)
        .order_by(Signal.coin_id.asc(), Signal.ts.asc())
    )
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        signal_stmt = signal_stmt.where(Signal.ts >= cutoff)
    if normalized_market is not None:
        signal_stmt = (
            select(Signal, Coin.market)
            .join(Coin, Signal.coin_id == Coin.id)
            .where(Coin.market == normalized_market)
            .order_by(Signal.coin_id.asc(), Signal.ts.asc())
        )
        if days is not None:
            signal_stmt = signal_stmt.where(Signal.ts >= cutoff)
    signal_result = await db.execute(signal_stmt)
    signal_rows = [
        {"signal": signal, "market": market, "ts": signal.ts, "side": signal.side}
        for signal, market in signal_result.all()
    ]

    trades = _build_closed_trades(fill_rows)
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        trades = [
            trade for trade in trades
            if datetime.fromisoformat(trade["exitTs"]) >= cutoff
        ]
    if normalized_market is not None:
        trades = [trade for trade in trades if trade["market"] == normalized_market]
    trades = trades[:limit]
    payload = {
        "summary": _summarize_performance(trades),
        "byMarket": _group_performance(trades, "market"),
        "byExitReason": _group_performance(trades, "exitReason"),
        "byFinalScoreBand": _group_score_band_performance(trades),
        "bySentimentBand": _group_sentiment_band_performance(trades),
        "byHourBlock": _group_hour_block_performance(trades),
        "byTransition": _group_signal_transitions([row["signal"] for row in signal_rows]),
        "byMarketTransitionQuality": _group_market_transition_quality(signal_rows),
        "trades": trades,
    }
    redis_client = None
    try:
        redis_client = _get_redis()
        await redis_client.set(
            cache_key,
            json.dumps(payload),
            ex=PORTFOLIO_PERFORMANCE_CACHE_TTL_SECONDS,
        )
    except Exception:
        pass
    finally:
        if redis_client is not None:
            await redis_client.aclose()
    return payload


@router.get("/portfolio/transition-quality/{market}")
async def get_market_transition_quality(
    market: str,
    days: Optional[int] = Query(None, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    normalized_market = market.upper()
    signal_stmt = (
        select(Signal, Coin.market)
        .join(Coin, Signal.coin_id == Coin.id)
        .where(Coin.market == normalized_market)
        .order_by(Signal.coin_id.asc(), Signal.ts.asc())
    )
    if isinstance(days, int):
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        signal_stmt = signal_stmt.where(Signal.ts >= cutoff)

    signal_result = await db.execute(signal_stmt)
    signal_rows = [
        {"signal": signal, "market": market_code, "ts": signal.ts, "side": signal.side}
        for signal, market_code in signal_result.all()
    ]
    return _get_market_transition_quality(signal_rows, normalized_market)


@router.get("/portfolio/daily-report")
async def get_daily_report(db: AsyncSession = Depends(get_db)):
    start_utc = _current_kst_day_start_utc()
    date_key = _current_kst_date_key()
    analytics = await _build_daily_report_analytics(db, start_utc=start_utc, end_utc=None)
    trades = analytics["trades"]

    position_stmt = (
        select(Position, Coin.market)
        .join(Coin, Position.coin_id == Coin.id)
        .where(Position.qty > 0)
        .order_by(Position.unrealized_pnl.asc(), Coin.market.asc())
    )
    position_rows = (await db.execute(position_stmt)).all()

    redis_client = None
    excluded_state = {"markets": [], "items": []}
    daily_pnl_value = 0.0
    loss_streak = 0
    try:
        redis_client = _get_redis()
        daily_pnl_raw = await redis_client.get(f"risk:daily_pnl:{date_key}")
        loss_streak_raw = await redis_client.get(RISK_LOSS_STREAK_REDIS_KEY)
        excluded_raw = await redis_client.get(EXCLUDED_MARKETS_REDIS_KEY)
        if daily_pnl_raw is not None:
            daily_pnl_value = float(
                daily_pnl_raw.decode() if isinstance(daily_pnl_raw, bytes) else daily_pnl_raw
            )
        if loss_streak_raw is not None:
            loss_streak = int(
                loss_streak_raw.decode() if isinstance(loss_streak_raw, bytes) else loss_streak_raw
            )
        excluded_state = _parse_excluded_market_state(excluded_raw)
    finally:
        if redis_client is not None:
            await redis_client.aclose()

    payload = {
        "date": date_key,
        "summary": {
            "dailyPnl": sum(trade["netPnl"] for trade in trades),
            "runtimeRiskDailyPnl": daily_pnl_value,
            "lossStreak": loss_streak,
            "closedTrades": len(trades),
            "wins": sum(1 for trade in trades if trade["netPnl"] > 0),
            "losses": sum(1 for trade in trades if trade["netPnl"] < 0),
            "netPnl": sum(trade["netPnl"] for trade in trades),
            "openPositions": len(position_rows),
            "excludedMarkets": len(excluded_state["markets"]),
            "riskRejectedCount": analytics["riskRejectedCount"],
            "orderFailedCount": analytics["orderFailedCount"],
            "excludedOpsCount": analytics["excludedOpsCount"],
        },
        "byExitReason": analytics["byExitReason"],
        "analysis": analytics["analysis"],
        "positions": [
            {
                "market": market,
                "source": position.source,
                "qty": position.qty,
                "avgEntryPrice": position.avg_entry_price,
                "unrealizedPnl": position.unrealized_pnl,
                "realizedPnl": position.realized_pnl,
                "excluded": market in excluded_state["markets"],
                "excludedReason": next(
                    (
                        item["reason"]
                        for item in excluded_state["items"]
                        if item["market"] == market
                    ),
                    "",
                ),
            }
            for position, market in position_rows
        ],
        "recentAuditCounts": analytics["recentAuditCounts"],
    }
    await _persist_daily_report_snapshot(db, date_key, payload)
    return payload


@router.get("/portfolio/daily-report/history")
async def get_daily_report_history(
    limit: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(RuntimeState)
        .where(RuntimeState.key.like(f"{DAILY_REPORT_RUNTIME_STATE_PREFIX}%"))
        .order_by(RuntimeState.key.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    payloads = []
    for row in rows:
        payload = json.loads(row.value)
        date_key = str(payload.get("date") or row.key.removeprefix(DAILY_REPORT_RUNTIME_STATE_PREFIX))
        try:
            payload = await _backfill_daily_report_payload(db, date_key=date_key, payload=payload)
            if row.value != json.dumps(payload):
                await _persist_daily_report_snapshot(db, date_key, payload)
        except Exception:
            pass
        payloads.append(payload)
    return payloads

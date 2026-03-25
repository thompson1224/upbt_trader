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
from libs.db.models import Position, Coin, RuntimeState, Fill, Order, Signal
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


class PositionAutoTradeRequest(BaseModel):
    enabled: bool


def _get_redis():
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    return aioredis.from_url(redis_url)


def _position_management_key(coin_id: int) -> str:
    return f"{POSITION_SOURCE_OVERRIDE_KEY_PREFIX}{coin_id}"


def _performance_cache_key(limit: int, days: Optional[int], market: Optional[str]) -> str:
    range_key = "all" if days is None else f"{days}d"
    market_key = (market or "all").upper().replace(":", "_")
    return f"{PORTFOLIO_PERFORMANCE_CACHE_KEY_PREFIX}{limit}:{range_key}:{market_key}"


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
    states: dict[str, dict] = {}
    trades: list[dict] = []

    for row in fill_rows:
        market = row["market"]
        side = row["side"]
        volume = row["volume"]
        price = row["price"]
        fee = row["fee"]
        filled_at = row["filledAt"]

        if side == "bid":
            state = states.setdefault(
                market,
                {
                    "entryQty": 0.0,
                    "remainingQty": 0.0,
                    "entryFunds": 0.0,
                    "entryFee": 0.0,
                    "entryTs": filled_at,
                    "strategyId": row.get("strategyId"),
                    "taScore": row.get("taScore"),
                    "sentimentScore": row.get("sentimentScore"),
                    "finalScore": row.get("finalScore"),
                    "confidence": row.get("confidence"),
                },
            )
            state["entryQty"] += volume
            state["remainingQty"] += volume
            state["entryFunds"] += price * volume
            state["entryFee"] += fee
            if filled_at < state["entryTs"]:
                state["entryTs"] = filled_at
            continue

        state = states.get(market)
        if state is None or state["remainingQty"] <= 0:
            continue

        matched_qty = min(volume, state["remainingQty"])
        if matched_qty <= 0:
            continue

        exit_qty = state.get("exitQty", 0.0) + matched_qty
        exit_funds = state.get("exitFunds", 0.0) + (price * matched_qty)
        exit_fee = state.get("exitFee", 0.0) + (fee * (matched_qty / max(volume, 1e-12)))
        state["exitQty"] = exit_qty
        state["exitFunds"] = exit_funds
        state["exitFee"] = exit_fee
        state["exitTs"] = filled_at
        state["exitReason"] = _infer_exit_reason(
            row.get("signal"),
            row.get("orderReason"),
        )
        state["remainingQty"] -= matched_qty

        if state["remainingQty"] <= 1e-9 or isclose(state["remainingQty"], 0.0, abs_tol=1e-9):
            entry_qty = state["entryQty"]
            entry_funds = state["entryFunds"]
            entry_fee = state["entryFee"]
            gross_pnl = exit_funds - entry_funds
            net_pnl = gross_pnl - entry_fee - exit_fee
            trades.append(
                {
                    "market": market,
                    "entryTs": state["entryTs"].isoformat(),
                    "exitTs": state["exitTs"].isoformat(),
                    "entryPrice": entry_funds / max(entry_qty, 1e-12),
                    "exitPrice": exit_funds / max(exit_qty, 1e-12),
                    "qty": entry_qty,
                    "entryFee": entry_fee,
                    "exitFee": exit_fee,
                    "grossPnl": gross_pnl,
                    "netPnl": net_pnl,
                    "returnPct": (net_pnl / entry_funds) if entry_funds else 0.0,
                    "holdMinutes": max(
                        (state["exitTs"] - state["entryTs"]).total_seconds() / 60.0,
                        0.0,
                    ),
                    "exitReason": state.get("exitReason", "system"),
                    "strategyId": state.get("strategyId"),
                    "taScore": state.get("taScore"),
                    "sentimentScore": state.get("sentimentScore"),
                    "finalScore": state.get("finalScore"),
                    "confidence": state.get("confidence"),
                }
            )
            del states[market]

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


@router.get("/positions")
async def get_positions(db: AsyncSession = Depends(get_db)):
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
    for signal in signal_result.scalars():
        latest_signal_by_coin_id.setdefault(signal.coin_id, signal)
        if signal.side == "sell":
            latest_sell_signal_by_coin_id.setdefault(signal.coin_id, signal)

    payload = []
    for pos, market, coin_id in active_rows:
        latest_signal = latest_signal_by_coin_id.get(coin_id)
        latest_sell_signal = latest_sell_signal_by_coin_id.get(coin_id)
        current_price = _estimate_current_price(pos)
        reason_code, reason_text = _describe_sell_wait_reason(
            pos,
            latest_signal,
            latest_sell_signal,
            current_price,
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

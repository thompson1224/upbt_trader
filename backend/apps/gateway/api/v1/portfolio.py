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

router = APIRouter()
PORTFOLIO_EQUITY_CURVE_KEY = "portfolio:equity_curve"
PORTFOLIO_LATEST_SNAPSHOT_KEY = "portfolio:latest_snapshot"
PORTFOLIO_PERFORMANCE_CACHE_KEY_PREFIX = "portfolio:performance:v1:"
PORTFOLIO_PERFORMANCE_CACHE_TTL_SECONDS = 15
POSITION_SOURCE_STRATEGY = "strategy"
POSITION_SOURCE_EXTERNAL = "external"
POSITION_SOURCE_OVERRIDE_KEY_PREFIX = "position.management."


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


@router.get("/positions")
async def get_positions(db: AsyncSession = Depends(get_db)):
    stmt = select(Position, Coin.market).join(Coin)
    result = await db.execute(stmt)
    rows = result.all()
    return [
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
        }
        for pos, market in rows
        if pos.qty > 0
    ]


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

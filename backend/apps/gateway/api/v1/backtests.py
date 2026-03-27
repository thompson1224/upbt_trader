from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.backtest_service.engine.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    Trade,
)
from libs.db.models import (
    BacktestMetrics,
    BacktestRun,
    BacktestTrade,
    BacktestWindow,
    Candle1m,
    Coin,
)
from libs.db.session import get_db, get_session_factory

router = APIRouter()


class BacktestRunRequest(BaseModel):
    market: str
    strategy_id: str = "hybrid_v1"
    mode: str = "single"
    train_from: datetime
    train_to: datetime
    test_from: datetime
    test_to: datetime
    initial_equity: float = 1_000_000.0
    stop_loss_pct: float = 0.03
    take_profit_pct: float = 0.06
    test_window_days: int = 7
    step_days: int = 7


def _load_run_config(run: BacktestRun) -> dict:
    try:
        payload = json.loads(run.config_json)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


def _serialize_run(run: BacktestRun) -> dict:
    config = _load_run_config(run)
    return {
        "id": run.id,
        "market": config.get("market"),
        "strategy_id": run.strategy_id,
        "mode": config.get("mode", "single"),
        "status": run.status,
        "train_from": run.train_from,
        "train_to": run.train_to,
        "test_from": run.test_from,
        "test_to": run.test_to,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "error_message": run.error_message,
        "initial_equity": config.get("initial_equity"),
        "stop_loss_pct": config.get("stop_loss_pct"),
        "take_profit_pct": config.get("take_profit_pct"),
        "test_window_days": config.get("test_window_days"),
        "step_days": config.get("step_days"),
    }


def _serialize_window(window: BacktestWindow) -> dict:
    return {
        "id": window.id,
        "window_seq": window.window_seq,
        "train_from": window.train_from,
        "train_to": window.train_to,
        "test_from": window.test_from,
        "test_to": window.test_to,
        "start_equity": window.start_equity,
        "end_equity": window.end_equity,
        "net_pnl": window.net_pnl,
        "cagr": window.cagr,
        "sharpe": window.sharpe,
        "max_drawdown": window.max_drawdown,
        "win_rate": window.win_rate,
        "profit_factor": window.profit_factor,
        "total_trades": window.total_trades,
    }


def _validate_backtest_request(req: BacktestRunRequest) -> None:
    if req.train_from >= req.train_to:
        raise HTTPException(422, "train_from must be earlier than train_to")
    if req.test_from >= req.test_to:
        raise HTTPException(422, "test_from must be earlier than test_to")
    if req.initial_equity <= 0:
        raise HTTPException(422, "initial_equity must be positive")

    mode = req.mode.lower()
    if mode not in {"single", "walk_forward"}:
        raise HTTPException(422, "mode must be 'single' or 'walk_forward'")

    if mode == "walk_forward":
        if req.test_window_days < 1:
            raise HTTPException(422, "test_window_days must be >= 1")
        if req.step_days < 1:
            raise HTTPException(422, "step_days must be >= 1")
        if req.step_days < req.test_window_days:
            raise HTTPException(422, "step_days must be >= test_window_days")


def _build_walk_forward_windows(req: BacktestRunRequest) -> list[dict]:
    windows = []
    train_delta = req.train_to - req.train_from
    test_window_delta = timedelta(days=req.test_window_days)
    step_delta = timedelta(days=req.step_days)

    train_from = req.train_from
    train_to = req.train_to
    test_from = req.test_from
    seq = 1

    while test_from < req.test_to:
        test_to = min(test_from + test_window_delta, req.test_to)
        if test_to <= test_from:
            break
        windows.append(
            {
                "window_seq": seq,
                "train_from": train_from,
                "train_to": train_to,
                "test_from": test_from,
                "test_to": test_to,
            }
        )
        seq += 1
        train_from = train_from + step_delta
        train_to = train_from + train_delta
        test_from = test_from + step_delta

    return windows


def _compute_return_pct(pnl: float, fee: float, entry_price: float, qty: float) -> float:
    gross_value = entry_price * qty
    if gross_value <= 0:
        return 0.0
    return (pnl + fee) / gross_value


async def _load_coin_and_candles(req: BacktestRunRequest, db: AsyncSession):
    import pandas as pd

    coin_result = await db.execute(select(Coin).where(Coin.market == req.market.upper()))
    coin = coin_result.scalar_one_or_none()
    if not coin:
        raise ValueError(f"Market {req.market} not found")

    candle_result = await db.execute(
        select(Candle1m)
        .where(
            Candle1m.coin_id == coin.id,
            Candle1m.ts >= req.train_from,
            Candle1m.ts <= req.test_to,
        )
        .order_by(Candle1m.ts)
    )
    candles = candle_result.scalars().all()
    if len(candles) < 100:
        raise ValueError("Insufficient candle data for backtesting")

    df = pd.DataFrame(
        [
            {
                "ts": c.ts,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
                "value": c.value,
            }
            for c in candles
        ]
    )
    return coin, df


def _build_engine(req: BacktestRunRequest) -> BacktestEngine:
    config = BacktestConfig(
        market=req.market.upper(),
        strategy_id=req.strategy_id,
        initial_equity=req.initial_equity,
        stop_loss_pct=req.stop_loss_pct,
        take_profit_pct=req.take_profit_pct,
    )
    return BacktestEngine(config)


def _scale_result(result: BacktestResult, scale: float) -> BacktestResult:
    scaled_trades = [
        replace(
            trade,
            qty=trade.qty * scale,
            pnl=trade.pnl * scale,
            fee=trade.fee * scale,
            slippage=trade.slippage * scale,
        )
        for trade in result.trades
    ]
    scaled_equity_curve = [
        {"ts": point["ts"], "equity": float(point["equity"]) * scale}
        for point in result.equity_curve
    ]
    return BacktestResult(
        trades=scaled_trades,
        equity_curve=scaled_equity_curve,
        cagr=result.cagr,
        sharpe=result.sharpe,
        max_drawdown=result.max_drawdown,
        win_rate=result.win_rate,
        profit_factor=result.profit_factor,
        total_trades=result.total_trades,
    )


def _window_net_pnl(start_equity: float, equity_curve: list[dict]) -> float:
    if not equity_curve:
        return 0.0
    return float(equity_curve[-1]["equity"]) - start_equity


@router.post("/backtests/runs", status_code=202)
async def create_backtest_run(
    req: BacktestRunRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    _validate_backtest_request(req)

    run = BacktestRun(
        strategy_id=req.strategy_id,
        config_json=req.model_dump_json(),
        train_from=req.train_from,
        train_to=req.train_to,
        test_from=req.test_from,
        test_to=req.test_to,
        status="pending",
    )
    db.add(run)
    await db.flush()
    run_id = run.id
    background_tasks.add_task(_run_backtest, run_id, req)
    return {"run_id": run_id, "status": "pending"}


@router.get("/backtests/runs")
async def list_backtest_runs(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    runs = (await db.execute(select(BacktestRun).order_by(BacktestRun.id.desc()).limit(limit))).scalars().all()
    return [_serialize_run(run) for run in runs]


@router.get("/backtests/runs/{run_id}")
async def get_backtest_run(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(404, "Backtest run not found")
    return _serialize_run(run)


@router.get("/backtests/runs/{run_id}/metrics")
async def get_backtest_metrics(run_id: int, db: AsyncSession = Depends(get_db)):
    metrics = await db.execute(select(BacktestMetrics).where(BacktestMetrics.run_id == run_id))
    m = metrics.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Metrics not found")
    return {
        "cagr": m.cagr,
        "sharpe": m.sharpe,
        "max_drawdown": m.max_drawdown,
        "win_rate": m.win_rate,
        "profit_factor": m.profit_factor,
        "total_trades": m.total_trades,
    }


@router.get("/backtests/runs/{run_id}/trades")
async def get_backtest_trades(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(404, "Backtest run not found")

    rows = (
        await db.execute(
            select(BacktestTrade, Coin.market)
            .join(Coin, Coin.id == BacktestTrade.coin_id)
            .where(BacktestTrade.run_id == run_id)
            .order_by(BacktestTrade.entry_ts.desc())
        )
    ).all()

    payload = []
    for trade, market in rows:
        hold_minutes = 0.0
        if trade.exit_ts is not None:
            hold_minutes = max((trade.exit_ts - trade.entry_ts).total_seconds() / 60, 0.0)
        payload.append(
            {
                "id": trade.id,
                "market": market,
                "entry_ts": trade.entry_ts,
                "exit_ts": trade.exit_ts,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "qty": trade.qty,
                "pnl": trade.pnl,
                "fee": trade.fee,
                "return_pct": _compute_return_pct(trade.pnl, trade.fee, trade.entry_price, trade.qty),
                "hold_minutes": hold_minutes,
            }
        )
    return payload


@router.get("/backtests/runs/{run_id}/windows")
async def get_backtest_windows(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(404, "Backtest run not found")

    windows = (
        await db.execute(
            select(BacktestWindow)
            .where(BacktestWindow.run_id == run_id)
            .order_by(BacktestWindow.window_seq.asc())
        )
    ).scalars().all()
    return [_serialize_window(window) for window in windows]


async def _run_single_backtest(
    engine: BacktestEngine,
    df,
) -> BacktestResult:
    return await asyncio.get_event_loop().run_in_executor(None, engine.run, df)


async def _run_walk_forward_backtest(
    req: BacktestRunRequest,
    engine: BacktestEngine,
    df,
) -> tuple[BacktestResult, list[dict]]:
    window_specs = _build_walk_forward_windows(req)
    if not window_specs:
        raise ValueError("No walk-forward windows generated")

    aggregated_trades: list[Trade] = []
    aggregated_equity_curve: list[dict] = []
    windows_payload: list[dict] = []
    current_equity = req.initial_equity

    for spec in window_specs:
        mask = (df["ts"] >= spec["train_from"]) & (df["ts"] <= spec["test_to"])
        segment_df = df.loc[mask].reset_index(drop=True)
        if len(segment_df) < 100:
            continue

        raw_result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda segment_df=segment_df, trade_start_ts=spec["test_from"]: engine.run(
                segment_df,
                trade_start_ts=trade_start_ts,
            ),
        )
        scale = current_equity / req.initial_equity if req.initial_equity > 0 else 1.0
        scaled_result = _scale_result(raw_result, scale)
        net_pnl = _window_net_pnl(current_equity, scaled_result.equity_curve)
        end_equity = current_equity + net_pnl

        windows_payload.append(
            {
                **spec,
                "start_equity": current_equity,
                "end_equity": end_equity,
                "net_pnl": net_pnl,
                "result": scaled_result,
            }
        )
        aggregated_trades.extend(scaled_result.trades)
        aggregated_equity_curve.extend(scaled_result.equity_curve)
        current_equity = end_equity

    if not aggregated_equity_curve:
        raise ValueError("Insufficient candle data for walk-forward backtesting")

    aggregate_result = engine._compute_metrics(aggregated_trades, aggregated_equity_curve, req.initial_equity)
    return aggregate_result, windows_payload


async def _run_backtest(run_id: int, req: BacktestRunRequest):
    session_factory = get_session_factory()
    async with session_factory() as db:
        run = await db.get(BacktestRun, run_id)
        if not run:
            raise RuntimeError(f"Backtest run {run_id} not found")
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            coin, df = await _load_coin_and_candles(req, db)
            engine = _build_engine(req)

            if req.mode.lower() == "walk_forward":
                result, windows_payload = await _run_walk_forward_backtest(req, engine, df)
            else:
                result = await _run_single_backtest(engine, df.loc[(df["ts"] >= req.test_from) & (df["ts"] <= req.test_to)].reset_index(drop=True))
                windows_payload = [
                    {
                        "window_seq": 1,
                        "train_from": req.train_from,
                        "train_to": req.train_to,
                        "test_from": req.test_from,
                        "test_to": req.test_to,
                        "start_equity": req.initial_equity,
                        "end_equity": result.equity_curve[-1]["equity"] if result.equity_curve else req.initial_equity,
                        "net_pnl": _window_net_pnl(req.initial_equity, result.equity_curve),
                        "result": result,
                    }
                ]

            for trade in result.trades:
                bt_trade = BacktestTrade(
                    run_id=run_id,
                    coin_id=coin.id,
                    entry_ts=trade.entry_ts,
                    exit_ts=trade.exit_ts,
                    entry_price=trade.entry_price,
                    exit_price=trade.exit_price,
                    qty=trade.qty,
                    pnl=trade.pnl,
                    fee=trade.fee,
                )
                db.add(bt_trade)

            for window_payload in windows_payload:
                window_result: BacktestResult = window_payload["result"]
                db.add(
                    BacktestWindow(
                        run_id=run_id,
                        window_seq=window_payload["window_seq"],
                        train_from=window_payload["train_from"],
                        train_to=window_payload["train_to"],
                        test_from=window_payload["test_from"],
                        test_to=window_payload["test_to"],
                        start_equity=window_payload["start_equity"],
                        end_equity=window_payload["end_equity"],
                        net_pnl=window_payload["net_pnl"],
                        cagr=window_result.cagr,
                        sharpe=window_result.sharpe,
                        max_drawdown=window_result.max_drawdown,
                        win_rate=window_result.win_rate,
                        profit_factor=window_result.profit_factor,
                        total_trades=window_result.total_trades,
                    )
                )

            db.add(
                BacktestMetrics(
                    run_id=run_id,
                    cagr=result.cagr,
                    sharpe=result.sharpe,
                    max_drawdown=result.max_drawdown,
                    win_rate=result.win_rate,
                    profit_factor=result.profit_factor,
                    total_trades=result.total_trades,
                )
            )

            run.status = "completed"
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()

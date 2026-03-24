from __future__ import annotations
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from libs.db.session import get_db, get_session_factory
from libs.db.models import BacktestRun, BacktestMetrics, Coin, Candle1m
from apps.backtest_service.engine.backtest_engine import BacktestEngine, BacktestConfig

router = APIRouter()


class BacktestRunRequest(BaseModel):
    market: str
    strategy_id: str = "hybrid_v1"
    train_from: datetime
    train_to: datetime
    test_from: datetime
    test_to: datetime
    initial_equity: float = 1_000_000.0
    stop_loss_pct: float = 0.03
    take_profit_pct: float = 0.06


@router.post("/backtests/runs", status_code=202)
async def create_backtest_run(
    req: BacktestRunRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
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


@router.get("/backtests/runs/{run_id}")
async def get_backtest_run(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(404, "Backtest run not found")
    return {
        "id": run.id,
        "strategy_id": run.strategy_id,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "error_message": run.error_message,
    }


@router.get("/backtests/runs/{run_id}/metrics")
async def get_backtest_metrics(run_id: int, db: AsyncSession = Depends(get_db)):
    metrics = await db.execute(
        select(BacktestMetrics).where(BacktestMetrics.run_id == run_id)
    )
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


async def _run_backtest(run_id: int, req: BacktestRunRequest):
    """백그라운드 백테스트 실행."""
    import pandas as pd
    from libs.db.models import BacktestTrade

    session_factory = get_session_factory()
    async with session_factory() as db:
        run = await db.get(BacktestRun, run_id)
        if not run:
            raise RuntimeError(f"Backtest run {run_id} not found")
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            # 코인 조회
            coin_result = await db.execute(
                select(Coin).where(Coin.market == req.market.upper())
            )
            coin = coin_result.scalar_one_or_none()
            if not coin:
                raise ValueError(f"Market {req.market} not found")

            # 캔들 데이터 조회
            candle_result = await db.execute(
                select(Candle1m)
                .where(
                    Candle1m.coin_id == coin.id,
                    Candle1m.ts >= req.test_from,
                    Candle1m.ts <= req.test_to,
                )
                .order_by(Candle1m.ts)
            )
            candles = candle_result.scalars().all()
            if len(candles) < 100:
                raise ValueError("Insufficient candle data for backtesting")

            df = pd.DataFrame([
                {
                    "ts": c.ts, "open": c.open, "high": c.high,
                    "low": c.low, "close": c.close,
                    "volume": c.volume, "value": c.value,
                }
                for c in candles
            ])

            config = BacktestConfig(
                market=req.market,
                strategy_id=req.strategy_id,
                initial_equity=req.initial_equity,
                stop_loss_pct=req.stop_loss_pct,
                take_profit_pct=req.take_profit_pct,
            )
            engine = BacktestEngine(config)
            result = await asyncio.get_event_loop().run_in_executor(None, engine.run, df)

            # 결과 저장
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

            metrics = BacktestMetrics(
                run_id=run_id,
                cagr=result.cagr,
                sharpe=result.sharpe,
                max_drawdown=result.max_drawdown,
                win_rate=result.win_rate,
                profit_factor=result.profit_factor,
                total_trades=result.total_trades,
            )
            db.add(metrics)

            run.status = "completed"
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()

        except Exception as e:
            run.status = "failed"
            run.error_message = str(e)
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()

"""Backtest service entry point - 백테스트 작업 Polling 및 실행."""

import asyncio
import json
import logging
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import select, update

from apps.backtest_service.engine.backtest_engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    Trade,
)
from libs.config import get_settings
from libs.db.session import get_session_factory
from libs.db.models import (
    BacktestMetrics,
    BacktestRun,
    BacktestTrade,
    BacktestWindow,
    Candle1m,
    Coin,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 10
UPBIT_FEE_RATE = 0.0005


class BacktestWorker:
    def __init__(self):
        self.settings = get_settings()
        self.session_factory = get_session_factory()

    async def run(self):
        logger.info("Backtest service started.")
        while True:
            try:
                await self._process_pending_runs()
            except Exception as e:
                logger.error("Backtest worker error: %s", e)
            await asyncio.sleep(POLL_INTERVAL_SEC)

    async def _process_pending_runs(self):
        async with self.session_factory() as db:
            result = await db.execute(
                select(BacktestRun)
                .where(BacktestRun.status == "pending")
                .order_by(BacktestRun.id.asc())
                .limit(1)
            )
            run = result.scalar_one_or_none()
            if not run:
                return

            logger.info("Processing backtest run %d", run.id)
            run.status = "running"
            run.started_at = datetime.now(timezone.utc)
            await db.commit()

            try:
                config = json.loads(run.config_json)
                result_data = await self._execute_backtest(run, config)
                await self._save_results(run.id, result_data, config)
                run.status = "completed"
                run.finished_at = datetime.now(timezone.utc)
                logger.info("Backtest run %d completed", run.id)
            except Exception as exc:
                logger.error("Backtest run %d failed: %s", run.id, exc)
                run.status = "failed"
                run.error_message = str(exc)
                run.finished_at = datetime.now(timezone.utc)
            await db.commit()

    async def _execute_backtest(self, run: BacktestRun, config: dict) -> dict:
        market = config.get("market", "").upper()
        strategy_id = config.get("strategy_id", "hybrid_v1")
        initial_equity = config.get("initial_equity", 1_000_000.0)
        stop_loss_pct = config.get("stop_loss_pct", 0.03)
        take_profit_pct = config.get("take_profit_pct", 0.06)
        mode = config.get("mode", "single")
        test_window_days = config.get("test_window_days", 7)
        step_days = config.get("step_days", 7)

        async with self.session_factory() as db:
            coin_result = await db.execute(select(Coin).where(Coin.market == market))
            coin = coin_result.scalar_one_or_none()
            if not coin:
                raise ValueError(f"Market {market} not found")

            candle_result = await db.execute(
                select(Candle1m)
                .where(
                    Candle1m.coin_id == coin.id,
                    Candle1m.ts >= run.train_from,
                    Candle1m.ts <= run.test_to,
                )
                .order_by(Candle1m.ts)
            )
            candles = candle_result.scalars().all()
            if len(candles) < 100:
                raise ValueError(f"Insufficient candle data: {len(candles)} < 100")

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

        engine_config = BacktestConfig(
            market=market,
            strategy_id=strategy_id,
            initial_equity=initial_equity,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
        )
        engine = BacktestEngine(engine_config)

        if mode == "walk_forward":
            result, windows = await self._run_walk_forward(
                engine, df, config, initial_equity, test_window_days, step_days
            )
            return {"result": result, "windows": windows, "coin_id": coin.id}
        else:
            test_df = df[
                (df["ts"] >= run.test_from) & (df["ts"] <= run.test_to)
            ].reset_index(drop=True)
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: engine.run(test_df)
            )
            return {"result": result, "windows": [], "coin_id": coin.id}

    async def _run_walk_forward(
        self,
        engine: BacktestEngine,
        df: pd.DataFrame,
        config: dict,
        initial_equity: float,
        test_window_days: int,
        step_days: int,
    ) -> tuple[BacktestResult, list[dict]]:
        windows = []
        windows_payload = []
        train_from = config["train_from"]
        train_to = config["train_to"]
        test_from = config["test_from"]
        test_to = config["test_to"]
        train_delta = train_to - train_from
        test_window_delta = timedelta(days=test_window_days)
        step_delta = timedelta(days=step_days)
        seq = 1
        current_equity = initial_equity

        while test_from < test_to:
            test_end = min(test_from + test_window_delta, test_to)
            if test_end <= test_from:
                break

            mask = (df["ts"] >= train_from) & (df["ts"] <= test_end)
            segment_df = df.loc[mask].reset_index(drop=True)
            if len(segment_df) < 100:
                train_from = train_from + step_delta
                train_to = train_from + train_delta
                test_from = test_from + step_delta
                seq += 1
                continue

            raw_result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: engine.run(segment_df, trade_start_ts=test_from)
            )
            scale = current_equity / initial_equity if initial_equity > 0 else 1.0
            scaled_result = _scale_result(raw_result, scale)
            net_pnl = (
                float(scaled_result.equity_curve[-1]["equity"]) - current_equity
                if scaled_result.equity_curve
                else 0.0
            )
            end_equity = current_equity + net_pnl

            windows_payload.append(
                {
                    "window_seq": seq,
                    "train_from": train_from,
                    "train_to": train_to,
                    "test_from": test_from,
                    "test_to": test_end,
                    "start_equity": current_equity,
                    "end_equity": end_equity,
                    "net_pnl": net_pnl,
                    "result": scaled_result,
                }
            )
            windows.append(
                {
                    "window_seq": seq,
                    "train_from": train_from,
                    "train_to": train_to,
                    "test_from": test_from,
                    "test_to": test_end,
                    "start_equity": current_equity,
                    "end_equity": end_equity,
                    "net_pnl": net_pnl,
                    "cagr": scaled_result.cagr,
                    "sharpe": scaled_result.sharpe,
                    "max_drawdown": scaled_result.max_drawdown,
                    "win_rate": scaled_result.win_rate,
                    "profit_factor": scaled_result.profit_factor,
                    "total_trades": scaled_result.total_trades,
                }
            )
            current_equity = end_equity

            train_from = train_from + step_delta
            train_to = train_from + train_delta
            test_from = test_from + step_delta
            seq += 1

        aggregated_trades = []
        aggregated_equity = []
        for w in windows_payload:
            aggregated_trades.extend(w["result"].trades)
            aggregated_equity.extend(w["result"].equity_curve)
        aggregated_equity.sort(key=lambda x: x["ts"])

        aggregate_result = engine._compute_metrics(
            aggregated_trades, aggregated_equity, initial_equity
        )
        return aggregate_result, windows

    async def _save_results(self, run_id: int, data: dict, config: dict):
        result: BacktestResult = data["result"]
        windows: list[dict] = data["windows"]
        coin_id: int = data["coin_id"]

        async with self.session_factory() as db:
            for trade in result.trades:
                bt_trade = BacktestTrade(
                    run_id=run_id,
                    coin_id=coin_id,
                    entry_ts=trade.entry_ts,
                    exit_ts=trade.exit_ts,
                    entry_price=trade.entry_price,
                    exit_price=trade.exit_price,
                    qty=trade.qty,
                    pnl=trade.pnl,
                    fee=trade.fee,
                )
                db.add(bt_trade)

            for w in windows:
                db.add(
                    BacktestWindow(
                        run_id=run_id,
                        window_seq=w["window_seq"],
                        train_from=w["train_from"],
                        train_to=w["train_to"],
                        test_from=w["test_from"],
                        test_to=w["test_to"],
                        start_equity=w["start_equity"],
                        end_equity=w["end_equity"],
                        net_pnl=w["net_pnl"],
                        cagr=w.get("cagr"),
                        sharpe=w.get("sharpe"),
                        max_drawdown=w.get("max_drawdown"),
                        win_rate=w.get("win_rate"),
                        profit_factor=w.get("profit_factor"),
                        total_trades=w.get("total_trades"),
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
            await db.commit()


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


async def main():
    worker = BacktestWorker()
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())

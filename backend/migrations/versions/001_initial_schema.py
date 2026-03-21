"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-03-20
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # coins
    op.create_table(
        "coins",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("market", sa.String(20), nullable=False),
        sa.Column("base_currency", sa.String(10), nullable=False),
        sa.Column("quote_currency", sa.String(10), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("market_warning", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("market", name="uq_coins_market"),
    )
    op.create_index("ix_coins_market", "coins", ["market"])

    # candles_1m
    op.create_table(
        "candles_1m",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("coin_id", sa.Integer, sa.ForeignKey("coins.id"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float, nullable=False),
        sa.Column("high", sa.Float, nullable=False),
        sa.Column("low", sa.Float, nullable=False),
        sa.Column("close", sa.Float, nullable=False),
        sa.Column("volume", sa.Float, nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.UniqueConstraint("coin_id", "ts", name="uq_candles_1m_coin_ts"),
    )
    op.create_index("ix_candles_1m_coin_ts_desc", "candles_1m", ["coin_id", "ts"])

    # indicator_snapshots
    op.create_table(
        "indicator_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("coin_id", sa.Integer, sa.ForeignKey("coins.id"), nullable=False),
        sa.Column("timeframe", sa.String(5), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rsi", sa.Float, nullable=True),
        sa.Column("macd", sa.Float, nullable=True),
        sa.Column("macd_signal", sa.Float, nullable=True),
        sa.Column("macd_hist", sa.Float, nullable=True),
        sa.Column("bb_upper", sa.Float, nullable=True),
        sa.Column("bb_mid", sa.Float, nullable=True),
        sa.Column("bb_lower", sa.Float, nullable=True),
        sa.Column("bb_pct", sa.Float, nullable=True),
        sa.Column("ema_20", sa.Float, nullable=True),
        sa.Column("ema_50", sa.Float, nullable=True),
        sa.Column("ta_score", sa.Float, nullable=True),
        sa.UniqueConstraint("coin_id", "timeframe", "ts", name="uq_indicator_coin_tf_ts"),
    )
    op.create_index("ix_indicator_coin_ts", "indicator_snapshots", ["coin_id", "ts"])

    # sentiment_snapshots
    op.create_table(
        "sentiment_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("coin_id", sa.Integer, sa.ForeignKey("coins.id"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("sentiment_score", sa.Float, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("keywords", sa.Text, nullable=True),
        sa.Column("raw_prompt_ref", sa.String(100), nullable=True),
    )
    op.create_index("ix_sentiment_coin_ts", "sentiment_snapshots", ["coin_id", "ts"])

    # signals
    op.create_table(
        "signals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("strategy_id", sa.String(50), nullable=False),
        sa.Column("coin_id", sa.Integer, sa.ForeignKey("coins.id"), nullable=False),
        sa.Column("timeframe", sa.String(5), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ta_score", sa.Float, nullable=False),
        sa.Column("sentiment_score", sa.Float, nullable=True),
        sa.Column("final_score", sa.Float, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column("suggested_stop_loss", sa.Float, nullable=True),
        sa.Column("suggested_take_profit", sa.Float, nullable=True),
        sa.Column("suggested_qty", sa.Float, nullable=True),
        sa.Column("rejection_reason", sa.String(200), nullable=True),
    )
    op.create_index("ix_signal_strategy_ts", "signals", ["strategy_id", "ts"])
    op.create_index("ix_signal_coin_ts", "signals", ["coin_id", "ts"])

    # orders
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("signal_id", sa.Integer, sa.ForeignKey("signals.id"), nullable=True),
        sa.Column("coin_id", sa.Integer, sa.ForeignKey("coins.id"), nullable=False),
        sa.Column("exchange_order_id", sa.String(100), nullable=True),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("ord_type", sa.String(20), nullable=False),
        sa.Column("price", sa.Float, nullable=True),
        sa.Column("volume", sa.Float, nullable=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="wait"),
        sa.Column("rejected_reason", sa.String(200), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("exchange_order_id", name="uq_orders_exchange_id"),
    )
    op.create_index("ix_orders_state_ts", "orders", ["state", "created_at"])

    # fills
    op.create_table(
        "fills",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("trade_uuid", sa.String(100), nullable=False),
        sa.Column("price", sa.Float, nullable=False),
        sa.Column("volume", sa.Float, nullable=False),
        sa.Column("fee", sa.Float, nullable=False, server_default="0"),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_fills_order_ts", "fills", ["order_id", "filled_at"])

    # positions
    op.create_table(
        "positions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("coin_id", sa.Integer, sa.ForeignKey("coins.id"), nullable=False),
        sa.Column("qty", sa.Float, nullable=False, server_default="0"),
        sa.Column("avg_entry_price", sa.Float, nullable=False, server_default="0"),
        sa.Column("unrealized_pnl", sa.Float, nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Float, nullable=False, server_default="0"),
        sa.Column("stop_loss", sa.Float, nullable=True),
        sa.Column("take_profit", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("coin_id", name="uq_positions_coin"),
    )

    # backtest_runs
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("strategy_id", sa.String(50), nullable=False),
        sa.Column("config_json", sa.Text, nullable=False),
        sa.Column("train_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("train_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("test_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("test_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # backtest_trades
    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("backtest_runs.id"), nullable=False),
        sa.Column("coin_id", sa.Integer, sa.ForeignKey("coins.id"), nullable=False),
        sa.Column("entry_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_price", sa.Float, nullable=False),
        sa.Column("exit_price", sa.Float, nullable=True),
        sa.Column("qty", sa.Float, nullable=False),
        sa.Column("pnl", sa.Float, nullable=False, server_default="0"),
        sa.Column("fee", sa.Float, nullable=False, server_default="0"),
        sa.Column("slippage", sa.Float, nullable=False, server_default="0"),
    )
    op.create_index("ix_backtest_trades_run_coin", "backtest_trades", ["run_id", "coin_id"])

    # backtest_metrics
    op.create_table(
        "backtest_metrics",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("backtest_runs.id"), nullable=False),
        sa.Column("cagr", sa.Float, nullable=True),
        sa.Column("sharpe", sa.Float, nullable=True),
        sa.Column("max_drawdown", sa.Float, nullable=True),
        sa.Column("win_rate", sa.Float, nullable=True),
        sa.Column("profit_factor", sa.Float, nullable=True),
        sa.Column("total_trades", sa.Integer, nullable=True),
        sa.Column("turnover", sa.Float, nullable=True),
        sa.UniqueConstraint("run_id", name="uq_backtest_metrics_run"),
    )


def downgrade() -> None:
    op.drop_table("backtest_metrics")
    op.drop_table("backtest_trades")
    op.drop_table("backtest_runs")
    op.drop_table("positions")
    op.drop_table("fills")
    op.drop_table("orders")
    op.drop_table("signals")
    op.drop_table("sentiment_snapshots")
    op.drop_table("indicator_snapshots")
    op.drop_table("candles_1m")
    op.drop_table("coins")

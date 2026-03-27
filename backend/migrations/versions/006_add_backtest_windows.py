"""add backtest windows

Revision ID: 006
Revises: 005
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backtest_windows",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("backtest_runs.id"), nullable=False),
        sa.Column("window_seq", sa.Integer, nullable=False),
        sa.Column("train_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("train_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("test_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("test_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_equity", sa.Float, nullable=False, server_default="0"),
        sa.Column("end_equity", sa.Float, nullable=False, server_default="0"),
        sa.Column("net_pnl", sa.Float, nullable=False, server_default="0"),
        sa.Column("cagr", sa.Float, nullable=True),
        sa.Column("sharpe", sa.Float, nullable=True),
        sa.Column("max_drawdown", sa.Float, nullable=True),
        sa.Column("win_rate", sa.Float, nullable=True),
        sa.Column("profit_factor", sa.Float, nullable=True),
        sa.Column("total_trades", sa.Integer, nullable=True),
    )
    op.create_index("ix_backtest_windows_run_seq", "backtest_windows", ["run_id", "window_seq"])


def downgrade() -> None:
    op.drop_index("ix_backtest_windows_run_seq", table_name="backtest_windows")
    op.drop_table("backtest_windows")

"""add performance indexes and fills unique constraint

- signals(status, ts): execution_service 핵심 폴링 쿼리 최적화
- fills(filled_at): 일별 P&L 재계산 성능
- fills(order_id, trade_uuid) UNIQUE: 중복 체결 삽입 방지

Revision ID: 008
Revises: 007
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # execution_service가 매 5초 폴링하는 핵심 쿼리: WHERE status='new' ORDER BY ts
    op.create_index("ix_signals_status_ts", "signals", ["status", "ts"])

    # 일별 P&L 재계산: WHERE filled_at >= day_start
    op.create_index("ix_fills_filled_at", "fills", ["filled_at"])

    # 중복 체결 방지: Upbit에서 동일 trade_uuid가 중복 수신될 경우 DB 레벨에서 차단
    op.create_unique_constraint(
        "uq_fills_order_trade_uuid", "fills", ["order_id", "trade_uuid"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_fills_order_trade_uuid", "fills", type_="unique")
    op.drop_index("ix_fills_filled_at", table_name="fills")
    op.drop_index("ix_signals_status_ts", table_name="signals")

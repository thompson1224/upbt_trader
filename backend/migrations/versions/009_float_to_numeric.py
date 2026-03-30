"""convert monetary columns from float to numeric

Float(IEEE 754)은 소수점 정밀도 손실이 발생할 수 있어 금융 계산에 부적합.
NUMERIC(20, 8)로 변환: 최대 999,999,999,999.99999999 표현 가능.

대상 테이블/컬럼:
  orders:    price, volume
  fills:     price, volume, fee
  positions: qty, avg_entry_price, unrealized_pnl, realized_pnl, stop_loss, take_profit

Revision ID: 009
Revises: 008
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None

NUMERIC = sa.Numeric(20, 8)
FLOAT = sa.Float()


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.alter_column("price", type_=NUMERIC, existing_type=FLOAT)
        batch_op.alter_column("volume", type_=NUMERIC, existing_type=FLOAT)

    with op.batch_alter_table("fills") as batch_op:
        batch_op.alter_column("price", type_=NUMERIC, existing_type=FLOAT)
        batch_op.alter_column("volume", type_=NUMERIC, existing_type=FLOAT)
        batch_op.alter_column("fee", type_=NUMERIC, existing_type=FLOAT)

    with op.batch_alter_table("positions") as batch_op:
        batch_op.alter_column("qty", type_=NUMERIC, existing_type=FLOAT)
        batch_op.alter_column("avg_entry_price", type_=NUMERIC, existing_type=FLOAT)
        batch_op.alter_column("unrealized_pnl", type_=NUMERIC, existing_type=FLOAT)
        batch_op.alter_column("realized_pnl", type_=NUMERIC, existing_type=FLOAT)
        batch_op.alter_column("stop_loss", type_=NUMERIC, existing_type=FLOAT)
        batch_op.alter_column("take_profit", type_=NUMERIC, existing_type=FLOAT)


def downgrade() -> None:
    with op.batch_alter_table("positions") as batch_op:
        batch_op.alter_column("take_profit", type_=FLOAT, existing_type=NUMERIC)
        batch_op.alter_column("stop_loss", type_=FLOAT, existing_type=NUMERIC)
        batch_op.alter_column("realized_pnl", type_=FLOAT, existing_type=NUMERIC)
        batch_op.alter_column("unrealized_pnl", type_=FLOAT, existing_type=NUMERIC)
        batch_op.alter_column("avg_entry_price", type_=FLOAT, existing_type=NUMERIC)
        batch_op.alter_column("qty", type_=FLOAT, existing_type=NUMERIC)

    with op.batch_alter_table("fills") as batch_op:
        batch_op.alter_column("fee", type_=FLOAT, existing_type=NUMERIC)
        batch_op.alter_column("volume", type_=FLOAT, existing_type=NUMERIC)
        batch_op.alter_column("price", type_=FLOAT, existing_type=NUMERIC)

    with op.batch_alter_table("orders") as batch_op:
        batch_op.alter_column("volume", type_=FLOAT, existing_type=NUMERIC)
        batch_op.alter_column("price", type_=FLOAT, existing_type=NUMERIC)

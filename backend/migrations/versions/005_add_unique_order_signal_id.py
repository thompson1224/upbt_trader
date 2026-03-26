"""add unique order signal id

Revision ID: 005
Revises: 004
Create Date: 2026-03-26
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_orders_signal_id", "orders", ["signal_id"])


def downgrade() -> None:
    op.drop_constraint("uq_orders_signal_id", "orders", type_="unique")


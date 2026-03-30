"""add position liquidating flag

SL/TP 중복 청산 방지용 원자적 클레임 컬럼 추가.
True이면 해당 포지션의 청산이 진행 중이므로 재진입 금지.

Revision ID: 007
Revises: 006
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "positions",
        sa.Column(
            "liquidating",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("positions", "liquidating")

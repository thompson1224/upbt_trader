"""add position source

Revision ID: 002
Revises: 001
Create Date: 2026-03-24
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "positions",
        sa.Column("source", sa.String(length=20), nullable=False, server_default="external"),
    )


def downgrade() -> None:
    op.drop_column("positions", "source")

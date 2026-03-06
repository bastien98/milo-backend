"""Add spins_available column to cashback_balances

Revision ID: 033_add_spins_available
Revises: 032_add_spins_awarded
Create Date: 2026-03-06
"""

from alembic import op
import sqlalchemy as sa

revision: str = "033_add_spins_available"
down_revision: str = "032_add_spins_awarded"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cashback_balances",
        sa.Column("spins_available", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("cashback_balances", "spins_available")

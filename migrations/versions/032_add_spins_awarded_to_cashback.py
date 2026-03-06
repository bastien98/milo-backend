"""Add spins_awarded column to cashback_transactions

Revision ID: 032_add_spins_awarded
Revises: 031_merge_heads
Create Date: 2026-03-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "032_add_spins_awarded"
down_revision: str = "031_merge_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cashback_transactions",
        sa.Column("spins_awarded", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("cashback_transactions", "spins_awarded")

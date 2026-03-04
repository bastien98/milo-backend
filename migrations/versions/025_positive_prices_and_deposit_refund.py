"""Positive prices, is_deposit_refund, drop total_savings

Revision ID: 025_positive_prices
Revises: 024_add_lookup_key
Create Date: 2026-03-04

1. Add is_deposit_refund boolean column to transactions
2. Drop total_savings column from receipts (never used by iOS or analytics)
3. Flip existing negative item_price values to positive (all prices now positive)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "025_positive_prices"
down_revision: str = "024_add_lookup_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add is_deposit_refund column
    op.add_column(
        "transactions",
        sa.Column("is_deposit_refund", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    # 2. Drop total_savings from receipts
    op.drop_column("receipts", "total_savings")

    # 3. Flip negative prices to positive
    op.execute("UPDATE transactions SET item_price = ABS(item_price) WHERE item_price < 0")


def downgrade() -> None:
    op.add_column(
        "receipts",
        sa.Column("total_savings", sa.Float(), nullable=True),
    )
    op.drop_column("transactions", "is_deposit_refund")
    # Note: cannot restore original negative prices — data loss on downgrade

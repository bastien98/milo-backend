"""Add custom_amount field to split_participants table

Revision ID: 004_add_custom_amount
Revises: 003_add_expense_splits
Create Date: 2026-02-03

This migration adds a custom_amount field to split_participants to support
custom split amounts (instead of equal splits).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004_add_custom_amount'
down_revision: Union[str, None] = '003_add_expense_splits'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add custom_amount column to split_participants table
    op.execute("""
        ALTER TABLE split_participants
        ADD COLUMN IF NOT EXISTS custom_amount FLOAT NULL
    """)


def downgrade() -> None:
    # Remove the custom_amount column
    op.execute("""
        ALTER TABLE split_participants DROP COLUMN IF EXISTS custom_amount
    """)

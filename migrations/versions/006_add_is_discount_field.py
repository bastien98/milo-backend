"""Add is_discount field to transactions table

Revision ID: 006_add_is_discount
Revises: 005_enriched_profiles
Create Date: 2026-02-05

This migration adds the is_discount field for tracking discount/bonus line items:
- is_discount: Boolean flag for discount lines (negative amounts like Hoeveelheidsvoordeel)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '006_add_is_discount'
down_revision: Union[str, None] = '005_enriched_profiles'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add is_discount column (discount/bonus line flag)
    op.execute("""
        ALTER TABLE transactions
        ADD COLUMN IF NOT EXISTS is_discount BOOLEAN NOT NULL DEFAULT FALSE
    """)


def downgrade() -> None:
    # Remove column
    op.execute("""
        ALTER TABLE transactions DROP COLUMN IF EXISTS is_discount
    """)

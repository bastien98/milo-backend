"""Add normalized_brand and is_premium fields to transactions table

Revision ID: 004_add_brand_premium
Revises: 003_add_normalized_fields
Create Date: 2026-02-03

This migration adds fields for brand tracking and premium classification:
- normalized_brand: Brand name for semantic search (lowercase)
- is_premium: Boolean flag for premium vs store/house brand
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004_add_brand_premium'
down_revision: Union[str, None] = '003_add_normalized_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add normalized_brand column (brand name for semantic search)
    op.execute("""
        ALTER TABLE transactions
        ADD COLUMN IF NOT EXISTS normalized_brand VARCHAR(255)
    """)

    # Add is_premium column (premium vs house brand flag)
    op.execute("""
        ALTER TABLE transactions
        ADD COLUMN IF NOT EXISTS is_premium BOOLEAN NOT NULL DEFAULT FALSE
    """)

    # Create index on normalized_brand for semantic search
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_transactions_normalized_brand
        ON transactions (normalized_brand)
    """)


def downgrade() -> None:
    # Drop index first
    op.execute("""
        DROP INDEX IF EXISTS ix_transactions_normalized_brand
    """)

    # Remove columns
    op.execute("""
        ALTER TABLE transactions DROP COLUMN IF EXISTS normalized_brand
    """)
    op.execute("""
        ALTER TABLE transactions DROP COLUMN IF EXISTS is_premium
    """)

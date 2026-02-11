"""Add normalized fields to transactions table

Revision ID: 003_add_normalized_fields
Revises: 002_add_receipt_source
Create Date: 2026-02-02

This migration adds fields for semantic search and granular categorization:
- original_description: Raw OCR text from receipt
- normalized_name: Cleaned name for semantic search (no quantities/packaging)
- is_deposit: Flag for Leeggoed/Vidange deposit items
- granular_category: Detailed category (~200 options)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_add_normalized_fields'
down_revision: Union[str, None] = '002_add_receipt_source'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add original_description column (raw OCR text)
    op.execute("""
        ALTER TABLE transactions
        ADD COLUMN IF NOT EXISTS original_description TEXT
    """)

    # Add normalized_name column (cleaned for semantic search)
    op.execute("""
        ALTER TABLE transactions
        ADD COLUMN IF NOT EXISTS normalized_name VARCHAR(255)
    """)

    # Add is_deposit column (Leeggoed/Vidange flag)
    op.execute("""
        ALTER TABLE transactions
        ADD COLUMN IF NOT EXISTS is_deposit BOOLEAN NOT NULL DEFAULT FALSE
    """)

    # Add granular_category column (detailed category)
    op.execute("""
        ALTER TABLE transactions
        ADD COLUMN IF NOT EXISTS granular_category VARCHAR(100)
    """)

    # Create index on normalized_name for semantic search
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_transactions_normalized_name
        ON transactions (normalized_name)
    """)

    # Create index on granular_category for filtering
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_transactions_granular_category
        ON transactions (granular_category)
    """)


def downgrade() -> None:
    # Drop indexes first
    op.execute("""
        DROP INDEX IF EXISTS ix_transactions_normalized_name
    """)
    op.execute("""
        DROP INDEX IF EXISTS ix_transactions_granular_category
    """)

    # Remove columns
    op.execute("""
        ALTER TABLE transactions DROP COLUMN IF EXISTS original_description
    """)
    op.execute("""
        ALTER TABLE transactions DROP COLUMN IF EXISTS normalized_name
    """)
    op.execute("""
        ALTER TABLE transactions DROP COLUMN IF EXISTS is_deposit
    """)
    op.execute("""
        ALTER TABLE transactions DROP COLUMN IF EXISTS granular_category
    """)

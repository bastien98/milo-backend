"""Add source field to receipts table

Revision ID: 002_add_receipt_source
Revises: 001_initial_banking
Create Date: 2026-02-02

This migration adds a source field to receipts to distinguish between
receipt uploads and bank imports. Also makes file metadata fields nullable
for bank imports which have no associated files.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_add_receipt_source'
down_revision: Union[str, None] = '001_initial_banking'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the receipt_source enum type
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE receiptsource AS ENUM ('receipt_upload', 'bank_import');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Add source column to receipts table with default value
    op.execute("""
        ALTER TABLE receipts
        ADD COLUMN IF NOT EXISTS source receiptsource NOT NULL DEFAULT 'receipt_upload'
    """)

    # Make file metadata fields nullable for bank imports
    op.execute("""
        ALTER TABLE receipts
        ALTER COLUMN original_filename DROP NOT NULL
    """)
    op.execute("""
        ALTER TABLE receipts
        ALTER COLUMN file_type DROP NOT NULL
    """)
    op.execute("""
        ALTER TABLE receipts
        ALTER COLUMN file_size_bytes DROP NOT NULL
    """)


def downgrade() -> None:
    # Remove the source column
    op.execute("""
        ALTER TABLE receipts DROP COLUMN IF EXISTS source
    """)

    # Restore NOT NULL constraints (may fail if there's data without these values)
    op.execute("""
        ALTER TABLE receipts
        ALTER COLUMN original_filename SET NOT NULL
    """)
    op.execute("""
        ALTER TABLE receipts
        ALTER COLUMN file_type SET NOT NULL
    """)
    op.execute("""
        ALTER TABLE receipts
        ALTER COLUMN file_size_bytes SET NOT NULL
    """)

    # Drop the enum type
    op.execute("""
        DROP TYPE IF EXISTS receiptsource
    """)

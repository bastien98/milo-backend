"""Add expense splits tables

Revision ID: 003_add_expense_splits
Revises: 002_add_receipt_source
Create Date: 2026-02-02

This migration creates tables for the expense splitting feature.
Uses IF NOT EXISTS to be safe for existing deployments.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_add_expense_splits'
down_revision: Union[str, None] = '002_add_receipt_source'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create expense_splits table
    op.execute("""
        CREATE TABLE IF NOT EXISTS expense_splits (
            id VARCHAR PRIMARY KEY,
            user_id VARCHAR NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            receipt_id VARCHAR NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE
        )
    """)

    # Create indexes for expense_splits
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_expense_splits_user_id
        ON expense_splits(user_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_expense_splits_receipt_id
        ON expense_splits(receipt_id)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_expense_splits_user_receipt
        ON expense_splits(user_id, receipt_id)
    """)

    # Create split_participants table
    op.execute("""
        CREATE TABLE IF NOT EXISTS split_participants (
            id VARCHAR PRIMARY KEY,
            split_id VARCHAR NOT NULL REFERENCES expense_splits(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            color VARCHAR(7) NOT NULL,
            display_order INTEGER DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)

    # Create indexes for split_participants
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_participants_split_id
        ON split_participants(split_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_participants_split_order
        ON split_participants(split_id, display_order)
    """)

    # Create split_assignments table
    op.execute("""
        CREATE TABLE IF NOT EXISTS split_assignments (
            id VARCHAR PRIMARY KEY,
            split_id VARCHAR NOT NULL REFERENCES expense_splits(id) ON DELETE CASCADE,
            transaction_id VARCHAR NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
            participant_ids JSONB NOT NULL DEFAULT '[]',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE
        )
    """)

    # Create indexes for split_assignments
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_assignments_split_id
        ON split_assignments(split_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_split_assignments_transaction_id
        ON split_assignments(transaction_id)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_split_assignments_split_transaction
        ON split_assignments(split_id, transaction_id)
    """)

    # Create recent_friends table for quick-add functionality
    op.execute("""
        CREATE TABLE IF NOT EXISTS recent_friends (
            id VARCHAR PRIMARY KEY,
            user_id VARCHAR NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            color VARCHAR(7) NOT NULL,
            last_used_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            use_count INTEGER DEFAULT 1
        )
    """)

    # Create indexes for recent_friends
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_recent_friends_user_id
        ON recent_friends(user_id)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_recent_friends_user_name
        ON recent_friends(user_id, name)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_recent_friends_user_last_used
        ON recent_friends(user_id, last_used_at)
    """)


def downgrade() -> None:
    # Drop tables in reverse order (respecting foreign keys)
    op.execute("DROP TABLE IF EXISTS recent_friends CASCADE")
    op.execute("DROP TABLE IF EXISTS split_assignments CASCADE")
    op.execute("DROP TABLE IF EXISTS split_participants CASCADE")
    op.execute("DROP TABLE IF EXISTS expense_splits CASCADE")

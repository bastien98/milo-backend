"""Restore original_description column on transactions.

Revision ID: 022_restore_original_description
Revises: 021_drop_original_desc
Create Date: 2026-02-28

Non-prod had a missing `transactions.original_description` column while runtime
models still select it, causing widespread 500s. This migration restores it.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "022_restore_original_description"
down_revision: Union[str, None] = "021_drop_original_desc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE transactions
        ADD COLUMN IF NOT EXISTS original_description TEXT
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE transactions
        DROP COLUMN IF EXISTS original_description
        """
    )


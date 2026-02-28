"""Recreate missing historical revision ID.

Revision ID: 021_drop_original_desc
Revises: 019_add_preferred_stores
Create Date: 2026-02-28

This is a no-op placeholder migration to restore a broken Alembic chain.
The revision was present in deployed database history but missing in source.
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "021_drop_original_desc"
down_revision: Union[str, None] = "019_add_preferred_stores"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No-op: this revision exists only to repair migration graph continuity.
    pass


def downgrade() -> None:
    # No-op placeholder.
    pass


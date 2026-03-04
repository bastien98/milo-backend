"""Drop expense split tables

Revision ID: 023_drop_split_tables
Revises: 022_add_storage_hash
Create Date: 2026-03-03

Removes the Split with Friends feature entirely.
Drops tables: split_assignments, split_participants, recent_friends, expense_splits.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "023_drop_split_tables"
down_revision: Union[str, None] = "022_add_storage_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS split_assignments")
    op.execute("DROP TABLE IF EXISTS split_participants")
    op.execute("DROP TABLE IF EXISTS recent_friends")
    op.execute("DROP TABLE IF EXISTS expense_splits")


def downgrade() -> None:
    # Tables are permanently removed; no downgrade supported.
    pass

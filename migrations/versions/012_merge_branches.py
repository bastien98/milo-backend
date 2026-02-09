"""Merge two migration branches after big-merge

Revision ID: 012_merge_branches
Revises: 006_add_is_discount, 011_split_categories
Create Date: 2026-02-09

Merge migration to unify the two parallel branches:
- Branch A (expense splits + category string migration): 003-011
- Branch B (normalized fields + enriched profiles): 003-006
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "012_merge_branches"
down_revision: tuple = ("006_add_is_discount", "011_split_categories")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

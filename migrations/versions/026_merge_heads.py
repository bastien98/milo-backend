"""Merge two migration branches into a single head.

Revision ID: 026_merge_heads
Revises: 022_restore_original_description, 025_positive_prices
Create Date: 2026-03-04
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "026_merge_heads"
down_revision = ("022_restore_original_description", "025_positive_prices")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

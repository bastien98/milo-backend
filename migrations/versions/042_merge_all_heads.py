"""Merge all migration heads

Revision ID: 042_merge_all_heads
Revises: 041_add_lottery_proof_image, bc0e8e7940f4
Create Date: 2026-03-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "042_merge_all_heads"
down_revision: Union[str, tuple] = ("041_add_lottery_proof_image", "bc0e8e7940f4")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

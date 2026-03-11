"""Add post_url to lottery_drawings

Revision ID: 043_add_post_url
Revises: 042_merge_all_heads
Create Date: 2026-03-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "043_add_post_url"
down_revision: str = "042_merge_all_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lottery_drawings", sa.Column("post_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("lottery_drawings", "post_url")

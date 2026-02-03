"""Add is_me column to split_participants

Revision ID: 005_add_is_me
Revises: 004_add_custom_amount
Create Date: 2026-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "005_add_is_me"
down_revision: Union[str, None] = "004_add_custom_amount"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add is_me column to split_participants table
    op.add_column(
        "split_participants",
        sa.Column("is_me", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("split_participants", "is_me")

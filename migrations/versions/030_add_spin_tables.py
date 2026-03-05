"""add spin tables

Revision ID: 030_add_spin_tables
Revises: 029_drop_health_score_and_original_description
Create Date: 2026-03-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "030_add_spin_tables"
down_revision: str = "029_drop_health_score_and_original_description"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "spin_transactions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("segment_label", sa.String(), nullable=False),
        sa.Column("segment_type", sa.String(), nullable=False),
        sa.Column("cash_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_jackpot", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_doubled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "spin_budget",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("total_budget", sa.Float(), nullable=False, server_default="1500"),
        sa.Column("total_spent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_spins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("spin_budget")
    op.drop_table("spin_transactions")

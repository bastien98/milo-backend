"""Drop user_rate_limits table (rate limiting removed).

Revision ID: 028_drop_user_rate_limits
Revises: 027_add_cashback_tables
Create Date: 2026-03-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "028_drop_user_rate_limits"
down_revision: str = "027_add_cashback_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_rate_limits CASCADE")


def downgrade() -> None:
    op.create_table(
        "user_rate_limits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("firebase_uid", sa.String(128), nullable=False),
        sa.Column("messages_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("receipts_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("period_start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["firebase_uid"], ["users.firebase_uid"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("firebase_uid"),
    )
    op.create_index(
        "ix_user_rate_limits_firebase_uid", "user_rate_limits", ["firebase_uid"]
    )

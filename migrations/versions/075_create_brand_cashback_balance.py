"""brand cashback: dedicated EUR-cents balance table

Revision ID: 075_create_brand_cashback_balance
Revises: 074_brand_cashback_pending_matches
Create Date: 2026-05-03

Introduces brand_cashback_balance — a per-user ledger denominated in EUR cents,
owned exclusively by the brand-cashback flow. The accompanying migration 076
drops the gamification tables (cashback_balances, spin/streak/lottery/etc.)
that previously held a points-based balance.

The app is pre-launch — there is no user data to backfill.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "075_create_brand_cashback_balance"
down_revision: Union[str, None] = "074_brand_cashback_pending_matches"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brand_cashback_balance",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "balance_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_earned_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_withdrawn_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_brand_cashback_balance_user_id",
        "brand_cashback_balance",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_brand_cashback_balance_user_id", table_name="brand_cashback_balance"
    )
    op.drop_table("brand_cashback_balance")

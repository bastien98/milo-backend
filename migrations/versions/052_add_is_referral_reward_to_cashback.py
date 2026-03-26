"""Add is_referral_reward to cashback_transactions

Revision ID: 052_add_is_referral_reward_to_cashback
Revises: 051_add_brand_cashback_tables
Create Date: 2026-03-25

Changes:
- Add is_referral_reward boolean column to cashback_transactions (default false)
  Allows fraud checks to distinguish genuine receipt scans from referral bonuses.
"""

revision = "052_add_is_referral_reward_to_cashback"
down_revision = "051_add_brand_cashback_tables"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    op.add_column(
        "cashback_transactions",
        sa.Column(
            "is_referral_reward",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("cashback_transactions", "is_referral_reward")

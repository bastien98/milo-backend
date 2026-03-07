"""Add referrer_reward_claimed and referee_reward_claimed to referrals table

Revision ID: 035_add_referral_claim_columns
Revises: 034_add_referral_system
Create Date: 2026-03-07
"""

from alembic import op
import sqlalchemy as sa

revision: str = "035_add_referral_claim_columns"
down_revision: str = "034_add_referral_system"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "referrals",
        sa.Column("referrer_reward_claimed", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "referrals",
        sa.Column("referee_reward_claimed", sa.Boolean(), nullable=False, server_default="false"),
    )

    # Backfill: existing rows with rewards_granted=True already had rewards auto-credited
    op.execute(
        "UPDATE referrals SET referrer_reward_claimed = true, referee_reward_claimed = true "
        "WHERE rewards_granted = true"
    )


def downgrade() -> None:
    op.drop_column("referrals", "referee_reward_claimed")
    op.drop_column("referrals", "referrer_reward_claimed")

"""Add referral system: referral_code/referred_by_code on user_profiles + referrals table

Revision ID: 034_add_referral_system
Revises: 033_add_spins_available
Create Date: 2026-03-07
"""

from alembic import op
import sqlalchemy as sa

revision: str = "034_add_referral_system"
down_revision: str = "033_add_spins_available"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add referral columns to user_profiles
    op.add_column(
        "user_profiles",
        sa.Column("referral_code", sa.String(10), nullable=True),
    )
    op.add_column(
        "user_profiles",
        sa.Column("referred_by_code", sa.String(10), nullable=True),
    )
    op.create_unique_constraint("uq_user_profiles_referral_code", "user_profiles", ["referral_code"])
    op.create_index("ix_user_profiles_referral_code", "user_profiles", ["referral_code"])

    # Create referrals table
    op.create_table(
        "referrals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("referrer_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("referee_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("referral_code", sa.String(10), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "completed", name="referralstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("rewards_granted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("referee_id", name="uq_referrals_referee_id"),
    )
    op.create_index("ix_referrals_referrer_id", "referrals", ["referrer_id"])
    op.create_index("ix_referrals_referee_id", "referrals", ["referee_id"])


def downgrade() -> None:
    op.drop_table("referrals")
    op.execute("DROP TYPE IF EXISTS referralstatus")
    op.drop_index("ix_user_profiles_referral_code", table_name="user_profiles")
    op.drop_constraint("uq_user_profiles_referral_code", "user_profiles", type_="unique")
    op.drop_column("user_profiles", "referred_by_code")
    op.drop_column("user_profiles", "referral_code")

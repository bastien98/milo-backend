"""Add streak_rewards table and streak columns to cashback_balances

Revision ID: 037_add_streak_rewards
Revises: 036_add_withdrawal_requests
Create Date: 2026-03-07
"""

from alembic import op
import sqlalchemy as sa

revision: str = "037_add_streak_rewards"
down_revision: str = "036_add_withdrawal_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enums
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE streakrewardstatus AS ENUM ('claimable', 'claimed'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE streakrewardtype AS ENUM ('spins', 'cash'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )

    # Create streak_rewards table
    op.execute("""
        CREATE TABLE streak_rewards (
            id VARCHAR NOT NULL PRIMARY KEY,
            user_id VARCHAR NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            week_number INTEGER NOT NULL,
            reward_type streakrewardtype NOT NULL,
            spins_amount INTEGER NOT NULL DEFAULT 0,
            cash_amount FLOAT NOT NULL DEFAULT 0.0,
            status streakrewardstatus NOT NULL DEFAULT 'claimable',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            claimed_at TIMESTAMP WITH TIME ZONE
        )
    """)
    op.create_index("ix_streak_rewards_user_id", "streak_rewards", ["user_id"])
    op.create_index("ix_streak_rewards_user_status", "streak_rewards", ["user_id", "status"])

    # Add streak columns to cashback_balances
    op.add_column("cashback_balances", sa.Column("streak_week_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("cashback_balances", sa.Column("streak_last_qualified_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("cashback_balances", "streak_last_qualified_at")
    op.drop_column("cashback_balances", "streak_week_count")
    op.drop_index("ix_streak_rewards_user_status", table_name="streak_rewards")
    op.drop_index("ix_streak_rewards_user_id", table_name="streak_rewards")
    op.drop_table("streak_rewards")
    op.execute("DROP TYPE IF EXISTS streakrewardtype")
    op.execute("DROP TYPE IF EXISTS streakrewardstatus")

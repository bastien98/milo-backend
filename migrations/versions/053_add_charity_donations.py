"""Add charity_donations table

Revision ID: 053_add_charity_donations
Revises: 052_add_is_referral_reward_to_cashback
Create Date: 2026-03-25

Changes:
- Create charitydonationstatus enum
- Create charity_donations table (id, user_id, charity_id, charity_name,
  amount, status, fraud_check_passed, fraud_check_details, created_at, transferred_at)
"""

revision = "053_add_charity_donations"
down_revision = "052_add_is_referral_reward_to_cashback"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE charitydonationstatus AS ENUM ('pending', 'transferred'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )

    op.execute("""
        CREATE TABLE charity_donations (
            id VARCHAR NOT NULL PRIMARY KEY,
            user_id VARCHAR NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            charity_id VARCHAR(64) NOT NULL,
            charity_name VARCHAR(128) NOT NULL,
            amount FLOAT NOT NULL,
            status charitydonationstatus NOT NULL DEFAULT 'pending',
            fraud_check_passed BOOLEAN NOT NULL DEFAULT FALSE,
            fraud_check_details JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            transferred_at TIMESTAMPTZ
        )
    """)

    op.execute("CREATE INDEX ix_charity_donations_user_id ON charity_donations(user_id)")
    op.execute("CREATE INDEX ix_charity_donations_charity_id ON charity_donations(charity_id)")
    op.execute("CREATE INDEX ix_charity_donations_status ON charity_donations(status)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS charity_donations")
    op.execute("DROP TYPE IF EXISTS charitydonationstatus")

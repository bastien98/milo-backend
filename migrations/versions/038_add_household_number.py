"""Add household_number column to user_profiles

Revision ID: 038_add_household_number
Revises: 037_add_streak_rewards
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa

revision: str = "038_add_household_number"
down_revision: str = "037_add_streak_rewards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Defensively add columns from migrations 018/019 that may be missing
    # due to alembic_version being out of sync with actual schema
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE user_profiles ADD COLUMN nickname VARCHAR;
        EXCEPTION WHEN duplicate_column THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE user_profiles ADD COLUMN age INTEGER;
        EXCEPTION WHEN duplicate_column THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE user_profiles ADD COLUMN language VARCHAR;
        EXCEPTION WHEN duplicate_column THEN null;
        END $$;
    """)

    op.add_column("user_profiles", sa.Column("household_number", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_profiles", "household_number")

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
    op.add_column("user_profiles", sa.Column("household_number", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_profiles", "household_number")

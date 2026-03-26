"""Add pending_review status to charity donations

Revision ID: 054_add_charity_pending_review
Revises: 053_add_charity_donations
Create Date: 2026-03-26

Changes:
- Add 'pending_review' value to charitydonationstatus enum
- Donations that fail fraud checks land in pending_review instead of pending
"""

revision = "054_add_charity_pending_review"
down_revision = "053_add_charity_donations"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    op.execute(
        "ALTER TYPE charitydonationstatus ADD VALUE IF NOT EXISTS 'pending_review' BEFORE 'pending'"
    )


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; requires manual intervention
    pass

"""Add rejected status to charity donations

Revision ID: 055_add_charity_rejected_status
Revises: 054_add_charity_pending_review
Create Date: 2026-03-26

Changes:
- Add 'rejected' value to charitydonationstatus enum
- Rejected donations have their balance refunded to the user
"""

revision = "055_add_charity_rejected_status"
down_revision = "054_add_charity_pending_review"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    op.execute(
        "ALTER TYPE charitydonationstatus ADD VALUE IF NOT EXISTS 'rejected'"
    )


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; requires manual intervention
    pass

"""Add category_profiles JSONB column to user_enriched_profiles

Revision ID: 052_add_category_profiles_column
Revises: 051_add_promo_items_table
Create Date: 2026-03-26

Changes:
- Add category_profiles JSONB column for promo-first matching engine
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "052_add_category_profiles_column"
down_revision = "051_add_promo_items_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_enriched_profiles",
        sa.Column("category_profiles", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_enriched_profiles", "category_profiles")

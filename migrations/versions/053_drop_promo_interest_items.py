"""Drop legacy promo_interest_items column from user_enriched_profiles

Revision ID: 053_drop_promo_interest_items
Revises: 052_add_category_profiles_column
Create Date: 2026-03-26

Changes:
- Drop promo_interest_items JSONB column (replaced by category_profiles)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "053_drop_promo_interest_items"
down_revision = "052_add_category_profiles_column"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("user_enriched_profiles", "promo_interest_items")


def downgrade() -> None:
    op.add_column(
        "user_enriched_profiles",
        sa.Column("promo_interest_items", JSONB, nullable=True),
    )

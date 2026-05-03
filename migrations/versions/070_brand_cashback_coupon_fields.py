"""brand cashback: coupon-grade campaign fields

Revision ID: 070_brand_cashback_coupon_fields
Revises: 069_brand_cashback_image_s3_key
Create Date: 2026-05-03

Adds the 7 fields the iOS UI was already built for plus curation/featured
flags so admins can author full coupon-app data:
  - terms (TEXT, nullable)
  - how_it_works (JSONB array of step strings)
  - claim_window_days (INTEGER, default 14)
  - max_redemptions_per_user (INTEGER, default 1)
  - total_redemption_cap (INTEGER, nullable = unlimited)
  - category (VARCHAR(32), nullable)
  - featured (BOOLEAN, default false)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "070_brand_cashback_coupon_fields"
down_revision: Union[str, None] = "069_brand_cashback_image_s3_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "brand_cashback_campaigns",
        sa.Column("terms", sa.Text(), nullable=True),
    )
    op.add_column(
        "brand_cashback_campaigns",
        sa.Column(
            "how_it_works",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "brand_cashback_campaigns",
        sa.Column(
            "claim_window_days",
            sa.Integer(),
            nullable=False,
            server_default="14",
        ),
    )
    op.add_column(
        "brand_cashback_campaigns",
        sa.Column(
            "max_redemptions_per_user",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "brand_cashback_campaigns",
        sa.Column("total_redemption_cap", sa.Integer(), nullable=True),
    )
    op.add_column(
        "brand_cashback_campaigns",
        sa.Column("category", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "brand_cashback_campaigns",
        sa.Column(
            "featured",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("brand_cashback_campaigns", "featured")
    op.drop_column("brand_cashback_campaigns", "category")
    op.drop_column("brand_cashback_campaigns", "total_redemption_cap")
    op.drop_column("brand_cashback_campaigns", "max_redemptions_per_user")
    op.drop_column("brand_cashback_campaigns", "claim_window_days")
    op.drop_column("brand_cashback_campaigns", "how_it_works")
    op.drop_column("brand_cashback_campaigns", "terms")

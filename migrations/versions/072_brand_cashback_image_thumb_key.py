"""brand cashback: add image_thumb_s3_key for separate thumbnail asset

Revision ID: 072_brand_cashback_image_thumb_key
Revises: 071_brand_cashback_drop_user_campaign_unique
Create Date: 2026-05-03

Adds a second image key per campaign so the iOS app can use a small,
square-cropped thumbnail in grid cards and a larger hero variant in
the detail sheet. image_s3_key continues to hold the hero (original
aspect, max 1200px); image_thumb_s3_key is the 400x400 square crop.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "072_brand_cashback_image_thumb_key"
down_revision: Union[str, None] = "071_brand_cashback_drop_user_campaign_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "brand_cashback_campaigns",
        sa.Column("image_thumb_s3_key", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("brand_cashback_campaigns", "image_thumb_s3_key")

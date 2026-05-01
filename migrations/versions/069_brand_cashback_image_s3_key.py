"""brand cashback: replace image_system_name with image_s3_key

Revision ID: 069_brand_cashback_image_s3_key
Revises: 068_promo_search_norm_columns
Create Date: 2026-05-01

Drops the SF Symbol identifier column and adds a nullable S3 key column
so admins can upload real product images. The app isn't live yet so no
data preservation is needed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "069_brand_cashback_image_s3_key"
down_revision: Union[str, None] = "068_promo_search_norm_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("brand_cashback_campaigns", "image_system_name")
    op.add_column(
        "brand_cashback_campaigns",
        sa.Column("image_s3_key", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("brand_cashback_campaigns", "image_s3_key")
    op.add_column(
        "brand_cashback_campaigns",
        sa.Column(
            "image_system_name",
            sa.String(),
            nullable=False,
            server_default="tag.fill",
        ),
    )

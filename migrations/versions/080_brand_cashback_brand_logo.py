"""brand cashback: add brand_logo_s3_key to campaigns

Revision ID: 080_brand_cashback_brand_logo
Revises: 079_brand_cashback_code_proposals
Create Date: 2026-05-05

Adds an optional brand-logo image per campaign, separate from the existing
product hero/thumb image. Stored as a single variant — logos are small UI
elements and a square center-crop would distort wordmark logos.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "080_brand_cashback_brand_logo"
down_revision: Union[str, None] = "079_brand_cashback_code_proposals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "brand_cashback_campaigns",
        sa.Column("brand_logo_s3_key", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("brand_cashback_campaigns", "brand_logo_s3_key")

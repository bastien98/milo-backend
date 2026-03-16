"""Add dp_product_name_no_brand to transactions

Revision ID: 045_add_dp_product_name_no_brand
Revises: 044_add_dp_packaging_type
Create Date: 2026-03-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "045_add_dp_product_name_no_brand"
down_revision: str = "044_add_dp_packaging_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("dp_product_name_no_brand", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("transactions", "dp_product_name_no_brand")

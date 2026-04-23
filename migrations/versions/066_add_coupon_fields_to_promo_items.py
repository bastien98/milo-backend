"""add coupon fields to promo_items

Revision ID: 066_add_coupon_fields_to_promo_items
Revises: 065_add_promo_item_bbox_overrides
Create Date: 2026-04-23

A coupon is a promo tile with a scannable 1D barcode users present at the till
to redeem loyalty points / cashback / free product / percentage discount.
This migration adds the fields needed to detect, store, and display such coupons.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "066_add_coupon_fields_to_promo_items"
down_revision: Union[str, None] = "065_add_promo_item_bbox_overrides"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "promo_items",
        sa.Column(
            "is_coupon",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("promo_items", sa.Column("coupon_type", sa.String(length=32), nullable=True))
    op.add_column("promo_items", sa.Column("coupon_barcode_value", sa.String(length=32), nullable=True))
    op.add_column("promo_items", sa.Column("coupon_barcode_format", sa.String(length=16), nullable=True))
    op.add_column("promo_items", sa.Column("coupon_value", sa.Float(), nullable=True))
    op.add_column("promo_items", sa.Column("coupon_min_purchase", sa.Text(), nullable=True))
    op.add_column("promo_items", sa.Column("coupon_validity_end", sa.Date(), nullable=True))
    op.add_column("promo_items", sa.Column("barcode_bbox_x_min", sa.Float(), nullable=True))
    op.add_column("promo_items", sa.Column("barcode_bbox_y_min", sa.Float(), nullable=True))
    op.add_column("promo_items", sa.Column("barcode_bbox_x_max", sa.Float(), nullable=True))
    op.add_column("promo_items", sa.Column("barcode_bbox_y_max", sa.Float(), nullable=True))

    # Partial index: coupons are the minority; only index the TRUE subset.
    op.execute(
        "CREATE INDEX ix_promo_items_is_coupon ON promo_items (is_coupon) WHERE is_coupon = TRUE"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_promo_items_is_coupon")
    op.drop_column("promo_items", "barcode_bbox_y_max")
    op.drop_column("promo_items", "barcode_bbox_x_max")
    op.drop_column("promo_items", "barcode_bbox_y_min")
    op.drop_column("promo_items", "barcode_bbox_x_min")
    op.drop_column("promo_items", "coupon_validity_end")
    op.drop_column("promo_items", "coupon_min_purchase")
    op.drop_column("promo_items", "coupon_value")
    op.drop_column("promo_items", "coupon_barcode_format")
    op.drop_column("promo_items", "coupon_barcode_value")
    op.drop_column("promo_items", "coupon_type")
    op.drop_column("promo_items", "is_coupon")

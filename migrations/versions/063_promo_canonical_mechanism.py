"""canonical promo mechanism + multi-brand + consumer category on promo_items

Revision ID: 063_promo_canonical_mechanism
Revises: 062_add_unit_pricing_fields
Create Date: 2026-04-20

Restructures promo_items around the schema redesign:

- Canonical mechanism fields (`mechanism_kind`, `mechanism_x`, `mechanism_y`)
  replace Gemini-authored free-text `display_mechanism`. Python derives
  display_mechanism from these via promo_folders_pipelines.mechanism.
- `promo_campaign`: store marketing banner verbatim ("Bonus", "Prix Choc", ...).
- `primary_brand` + `additional_brands` (JSONB): multi-product tiles extracted
  as one item instead of being split per brand.
- `stated_savings`: tile-printed "Bespaar €X" when present, separate from
  Python-derived `savings_amount`.
- `category`: parent-level consumer taxonomy (~22 values) derived from
  `granular_category` via app.core.categories.get_parent_category. iOS
  surfaces this; `granular_category` stays the similarity ranking key.

Pricing columns relaxed to NULL — some tiles legitimately lack a printed
original_price or promo_price (per-kg fresh goods, stated_savings-only tiles).

All new columns nullable so the migration is non-blocking. Backfill can run
on the next scheduled folder refresh.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "063_promo_canonical_mechanism"
down_revision: Union[str, None] = "062_add_unit_pricing_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("promo_items", sa.Column("mechanism_kind", sa.String(length=32), nullable=True))
    op.add_column("promo_items", sa.Column("mechanism_x", sa.Float(), nullable=True))
    op.add_column("promo_items", sa.Column("mechanism_y", sa.Float(), nullable=True))
    op.add_column("promo_items", sa.Column("promo_campaign", sa.String(length=64), nullable=True))
    op.add_column("promo_items", sa.Column("primary_brand", sa.String(length=255), nullable=True))
    op.add_column("promo_items", sa.Column("additional_brands", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("promo_items", sa.Column("stated_savings", sa.Float(), nullable=True))
    op.add_column("promo_items", sa.Column("category", sa.String(length=64), nullable=True))

    op.alter_column("promo_items", "original_price", existing_type=sa.Float(), nullable=True)
    op.alter_column("promo_items", "promo_price", existing_type=sa.Float(), nullable=True)

    op.create_index("ix_promo_items_mechanism_kind", "promo_items", ["mechanism_kind"])


def downgrade() -> None:
    op.drop_index("ix_promo_items_mechanism_kind", table_name="promo_items")

    op.alter_column("promo_items", "promo_price", existing_type=sa.Float(), nullable=False)
    op.alter_column("promo_items", "original_price", existing_type=sa.Float(), nullable=False)

    op.drop_column("promo_items", "category")
    op.drop_column("promo_items", "stated_savings")
    op.drop_column("promo_items", "additional_brands")
    op.drop_column("promo_items", "primary_brand")
    op.drop_column("promo_items", "promo_campaign")
    op.drop_column("promo_items", "mechanism_y")
    op.drop_column("promo_items", "mechanism_x")
    op.drop_column("promo_items", "mechanism_kind")

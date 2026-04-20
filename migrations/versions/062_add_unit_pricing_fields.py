"""add unit-pricing fields to promo_items

Revision ID: 062_add_unit_pricing_fields
Revises: 061_promo_similarity_and_drop_reports
Create Date: 2026-04-20

Adds numeric unit-price and raw pack-size fields so the B2B data product can
query/sort/compare €/kg across retailers, and so the extraction pipeline can
compute unit prices deterministically in Python rather than asking Gemini to
do arithmetic.

- unit_price_value / unit_price_unit: canonical €/kg, €/L, €/stuk, €/rol
- pack_size_value / pack_size_unit / pack_count: raw tokens from Gemini
- unit_price_quality: 'high' | 'medium' | 'low' | 'backfilled' | 'missing'

All columns nullable; pack_count defaults to 1 for existing rows.
Composite index on (granular_category, unit_price_unit, unit_price_value)
for the data-platform query path.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '062_add_unit_pricing_fields'
down_revision: Union[str, None] = '061_promo_similarity_and_drop_reports'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('promo_items', sa.Column('unit_price_value', sa.Float(), nullable=True))
    op.add_column('promo_items', sa.Column('unit_price_unit', sa.String(length=10), nullable=True))
    op.add_column('promo_items', sa.Column('pack_size_value', sa.Float(), nullable=True))
    op.add_column('promo_items', sa.Column('pack_size_unit', sa.String(length=16), nullable=True))
    op.add_column(
        'promo_items',
        sa.Column('pack_count', sa.Integer(), nullable=False, server_default='1'),
    )
    op.add_column('promo_items', sa.Column('unit_price_quality', sa.String(length=16), nullable=True))

    op.create_index(
        'ix_promo_items_unit_price',
        'promo_items',
        ['granular_category', 'unit_price_unit', 'unit_price_value'],
    )


def downgrade() -> None:
    op.drop_index('ix_promo_items_unit_price', table_name='promo_items')
    op.drop_column('promo_items', 'unit_price_quality')
    op.drop_column('promo_items', 'pack_count')
    op.drop_column('promo_items', 'pack_size_unit')
    op.drop_column('promo_items', 'pack_size_value')
    op.drop_column('promo_items', 'unit_price_unit')
    op.drop_column('promo_items', 'unit_price_value')

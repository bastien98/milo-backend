"""add brand fields to promo_items

Revision ID: 057_add_brand_fields_to_promo_items
Revises: 056_merge_heads
Create Date: 2026-03-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '057_add_brand_fields_to_promo_items'
down_revision: Union[str, None] = '056_merge_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('promo_items', sa.Column('normalized_brand', sa.String(255), nullable=True))
    op.add_column('promo_items', sa.Column('display_brand', sa.String(255), nullable=True))
    op.create_index('ix_promo_items_normalized_brand', 'promo_items', ['normalized_brand'])


def downgrade() -> None:
    op.drop_index('ix_promo_items_normalized_brand', table_name='promo_items')
    op.drop_column('promo_items', 'display_brand')
    op.drop_column('promo_items', 'normalized_brand')

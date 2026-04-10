"""add image url fields to promo_items

Revision ID: 058_add_image_urls_to_promo_items
Revises: 057_add_brand_fields_to_promo_items
Create Date: 2026-04-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '058_add_image_urls_to_promo_items'
down_revision: Union[str, None] = '057_add_brand_fields_to_promo_items'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('promo_items', sa.Column('thumbnail_url', sa.Text(), nullable=True))
    op.add_column('promo_items', sa.Column('image_url', sa.Text(), nullable=True))
    op.add_column('promo_items', sa.Column('hero_url', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('promo_items', 'hero_url')
    op.drop_column('promo_items', 'image_url')
    op.drop_column('promo_items', 'thumbnail_url')

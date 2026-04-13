"""add bounding box columns to promo_items

Revision ID: 059_add_bbox_columns_to_promo_items
Revises: 058_add_image_urls_to_promo_items
Create Date: 2026-04-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '059_add_bbox_columns_to_promo_items'
down_revision: Union[str, None] = '058_add_image_urls_to_promo_items'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Product bounding box (physical product only, for image cropping)
    op.add_column('promo_items', sa.Column('bbox_x_min', sa.Float(), nullable=True))
    op.add_column('promo_items', sa.Column('bbox_y_min', sa.Float(), nullable=True))
    op.add_column('promo_items', sa.Column('bbox_x_max', sa.Float(), nullable=True))
    op.add_column('promo_items', sa.Column('bbox_y_max', sa.Float(), nullable=True))
    # Tile bounding box (full promo tile area, for tap hotspots)
    op.add_column('promo_items', sa.Column('tile_bbox_x_min', sa.Float(), nullable=True))
    op.add_column('promo_items', sa.Column('tile_bbox_y_min', sa.Float(), nullable=True))
    op.add_column('promo_items', sa.Column('tile_bbox_x_max', sa.Float(), nullable=True))
    op.add_column('promo_items', sa.Column('tile_bbox_y_max', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('promo_items', 'tile_bbox_y_max')
    op.drop_column('promo_items', 'tile_bbox_x_max')
    op.drop_column('promo_items', 'tile_bbox_y_min')
    op.drop_column('promo_items', 'tile_bbox_x_min')
    op.drop_column('promo_items', 'bbox_y_max')
    op.drop_column('promo_items', 'bbox_x_max')
    op.drop_column('promo_items', 'bbox_y_min')
    op.drop_column('promo_items', 'bbox_x_min')

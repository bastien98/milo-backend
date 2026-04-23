"""add promo_item_bbox_overrides table

Revision ID: 065_add_promo_item_bbox_overrides
Revises: 064_add_promo_text_markdown
Create Date: 2026-04-23

Manual bbox corrections that survive every re-ingest of a folder.
Keyed on (promo_folder_url, page_number, display_name_normalized).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "065_add_promo_item_bbox_overrides"
down_revision: Union[str, None] = "064_add_promo_text_markdown"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "promo_item_bbox_overrides",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("promo_folder_url", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("display_name_normalized", sa.Text(), nullable=False),
        sa.Column("tile_bbox_x_min", sa.Float(), nullable=False),
        sa.Column("tile_bbox_y_min", sa.Float(), nullable=False),
        sa.Column("tile_bbox_x_max", sa.Float(), nullable=False),
        sa.Column("tile_bbox_y_max", sa.Float(), nullable=False),
        sa.Column("bbox_x_min", sa.Float(), nullable=True),
        sa.Column("bbox_y_min", sa.Float(), nullable=True),
        sa.Column("bbox_x_max", sa.Float(), nullable=True),
        sa.Column("bbox_y_max", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "promo_folder_url",
            "page_number",
            "display_name_normalized",
            name="uq_promo_item_bbox_overrides_folder_page_name",
        ),
    )
    op.create_index(
        "ix_promo_item_bbox_overrides_folder_page",
        "promo_item_bbox_overrides",
        ["promo_folder_url", "page_number"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_promo_item_bbox_overrides_folder_page",
        table_name="promo_item_bbox_overrides",
    )
    op.drop_table("promo_item_bbox_overrides")

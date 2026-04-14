"""make promo_items.promo_folder_url NOT NULL

Revision ID: 060_promo_folder_url_not_null
Revises: 059_add_bbox_columns_to_promo_items
Create Date: 2026-04-14

Rationale: hotspots are scoped per folder via promo_folder_url (the per-folder
promopromo source_url). Enforcing NOT NULL makes ingestion fail loudly if a
PDF entry in the week-level metadata.json is missing the folder URL, which
would otherwise cause hotspots to leak across folders of the same store.

Pre-flight cleanup deletes any rows that slipped in without a folder URL —
they can't be correctly attributed to a folder.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '060_promo_folder_url_not_null'
down_revision: Union[str, None] = '059_add_bbox_columns_to_promo_items'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM promo_items "
        "WHERE promo_folder_url IS NULL OR promo_folder_url = ''"
    )
    op.alter_column(
        'promo_items',
        'promo_folder_url',
        existing_type=sa.Text(),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        'promo_items',
        'promo_folder_url',
        existing_type=sa.Text(),
        nullable=True,
    )

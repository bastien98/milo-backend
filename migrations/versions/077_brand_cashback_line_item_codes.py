"""brand cashback: per-line-item product codes (EAN/artikel nummer)

Revision ID: 077_brand_cashback_line_item_codes
Revises: 076_drop_legacy_gamification
Create Date: 2026-05-04

Adds product_codes (JSONB array) to brand_cashback_store_line_items so admins
can pin a SKU by EAN (Delhaize) or artikel nummer (Colruyt). When set, the
matcher routes that line item to code-only mode (no text fallback). When empty,
the line item keeps the existing text Pass 1 + fuzzy Pass 2 behaviour — used by
chains that don't print per-line codes (Albert Heijn, Carrefour, Aldi, Lidl).

GIN index supports the JSONB containment lookup used by find_line_items_by_code.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "077_brand_cashback_line_item_codes"
down_revision: Union[str, None] = "076_drop_legacy_gamification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "brand_cashback_store_line_items",
        sa.Column(
            "product_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    op.create_index(
        "ix_brand_cashback_line_items_codes",
        "brand_cashback_store_line_items",
        ["product_codes"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_brand_cashback_line_items_codes",
        table_name="brand_cashback_store_line_items",
    )
    op.drop_column("brand_cashback_store_line_items", "product_codes")

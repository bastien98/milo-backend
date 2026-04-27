"""promo search infra: unaccent + search_text/generic_product_type + GIN trgm indexes

Revision ID: 067_promo_search_indexes
Revises: 066_add_coupon_fields_to_promo_items
Create Date: 2026-04-25

Adds the columns and indexes that power the /api/v2/promos/search endpoint:
  - unaccent extension so NL/FR product names match across diacritics
    ('cote dor' == 'côte d'or').
  - search_text (TEXT): Gemini-emitted blob of brand + name + multilingual
    generic noun + flavor variants. GIN trigram index for fuzzy lookup.
  - generic_product_type (VARCHAR(64)): single English noun for cross-brand
    matching. GIN trigram index.
  - GIN trigram indexes on display_brand and normalized_brand so brand
    fuzzy matches no longer fall back to seq scans.

Indexes are created CONCURRENTLY (no table locks) — production has live
traffic. Concurrent index creation cannot run inside a transaction, so the
migration disables Alembic's transaction-per-migration wrapper.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "067_promo_search_indexes"
down_revision: Union[str, None] = "066_add_coupon_fields_to_promo_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Columns first (transactional).
    op.add_column("promo_items", sa.Column("search_text", sa.Text(), nullable=True))
    op.add_column(
        "promo_items",
        sa.Column("generic_product_type", sa.String(length=64), nullable=True),
    )

    # Extension + concurrent index creation must run outside a transaction.
    # autocommit_block tells Alembic to commit before each statement.
    with op.get_context().autocommit_block():
        op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_promo_items_search_text_trgm "
            "ON promo_items USING gin (search_text gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_promo_items_generic_type_trgm "
            "ON promo_items USING gin (generic_product_type gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_promo_items_display_brand_trgm "
            "ON promo_items USING gin (display_brand gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_promo_items_normalized_brand_trgm "
            "ON promo_items USING gin (normalized_brand gin_trgm_ops)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_promo_items_normalized_brand_trgm")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_promo_items_display_brand_trgm")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_promo_items_generic_type_trgm")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_promo_items_search_text_trgm")

    op.drop_column("promo_items", "generic_product_type")
    op.drop_column("promo_items", "search_text")

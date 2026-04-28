"""promo search: persisted normalized columns + GIN trgm indexes

Revision ID: 068_promo_search_norm_columns
Revises: 067_promo_search_indexes
Create Date: 2026-04-28

Replaces the per-row `unaccent(lower(...))` wrappers in the /promos/search
query with stored generated columns. The previous migration's GIN trgm
indexes were never used by the planner because the query expressions
(`unaccent(lower(display_name))`) didn't match the indexed expression
(`display_name`). pg_stat_user_indexes confirmed: 1-6 lifetime scans on
the four trgm indexes vs. 4,646 on ix_promo_items_validity.

This migration:
  1. Adds an IMMUTABLE wrapper around `unaccent`. unaccent is STABLE in
     core because the dictionary contents could in theory change; for our
     fixed dictionary it's deterministic, and we need IMMUTABLE so the
     function can be referenced from a STORED generated column expression.
  2. Adds four STORED generated columns (display_name_norm,
     display_brand_norm, search_text_norm, generic_product_type_norm)
     each computed as f_unaccent(lower(coalesce(col, ''))). Postgres
     populates these on every INSERT/UPDATE — no ingest pipeline change
     needed.
  3. Builds GIN trigram indexes on the four new columns (CONCURRENTLY).

The four old trgm indexes (display_name_trgm, search_text_trgm,
display_brand_trgm, normalized_brand_trgm, generic_type_trgm) are
deliberately NOT dropped here:
  - ix_promo_items_display_name_trgm is still used by the similarity
    service (similarity(display_name, ...) raw, case-sensitive).
  - ix_promo_items_normalized_brand_trgm same situation.
  - The other three are unused but cheap to leave; we'll prune in a
    follow-up once we've observed the new indexes' usage stats.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "068_promo_search_norm_columns"
down_revision: Union[str, None] = "067_promo_search_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # f_unaccent: IMMUTABLE wrapper. The two-arg form pins the dictionary
    # explicitly, which is what makes the result truly deterministic for
    # our deployment. Standard recipe (PostgreSQL wiki, depesz).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION f_unaccent(text) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT AS
        $$ SELECT public.unaccent('public.unaccent', $1) $$
        """
    )

    # Generated columns. coalesce() so nullable columns produce '' (empty
    # string) rather than NULL — keeps the GIN trgm index dense and
    # avoids OR coalesce(...) gymnastics in the query.
    op.execute(
        """
        ALTER TABLE promo_items
          ADD COLUMN display_name_norm TEXT
            GENERATED ALWAYS AS (f_unaccent(lower(display_name))) STORED
        """
    )
    op.execute(
        """
        ALTER TABLE promo_items
          ADD COLUMN display_brand_norm TEXT
            GENERATED ALWAYS AS (f_unaccent(lower(coalesce(display_brand, '')))) STORED
        """
    )
    op.execute(
        """
        ALTER TABLE promo_items
          ADD COLUMN search_text_norm TEXT
            GENERATED ALWAYS AS (f_unaccent(lower(coalesce(search_text, '')))) STORED
        """
    )
    op.execute(
        """
        ALTER TABLE promo_items
          ADD COLUMN generic_product_type_norm TEXT
            GENERATED ALWAYS AS (f_unaccent(lower(coalesce(generic_product_type, '')))) STORED
        """
    )

    # GIN trigram indexes on the new columns. CONCURRENTLY → outside a
    # transaction (autocommit_block).
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_promo_items_display_name_norm_trgm "
            "ON promo_items USING gin (display_name_norm gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_promo_items_display_brand_norm_trgm "
            "ON promo_items USING gin (display_brand_norm gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_promo_items_search_text_norm_trgm "
            "ON promo_items USING gin (search_text_norm gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_promo_items_generic_product_type_norm_trgm "
            "ON promo_items USING gin (generic_product_type_norm gin_trgm_ops)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_promo_items_generic_product_type_norm_trgm")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_promo_items_search_text_norm_trgm")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_promo_items_display_brand_norm_trgm")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_promo_items_display_name_norm_trgm")

    op.execute("ALTER TABLE promo_items DROP COLUMN IF EXISTS generic_product_type_norm")
    op.execute("ALTER TABLE promo_items DROP COLUMN IF EXISTS search_text_norm")
    op.execute("ALTER TABLE promo_items DROP COLUMN IF EXISTS display_brand_norm")
    op.execute("ALTER TABLE promo_items DROP COLUMN IF EXISTS display_name_norm")

    op.execute("DROP FUNCTION IF EXISTS f_unaccent(text)")

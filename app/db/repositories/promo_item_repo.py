import re
from datetime import date
from typing import Any, Optional, Sequence

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.promo_item import PromoItem


def _interleave_by_store(
    rows: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """Round-robin search results across retailers within score-tied buckets.

    Without this, a retailer that uploaded more tiles for a given category in
    a given week monopolizes the visible top of the search results — e.g. a
    Colruyt-heavy week makes the first 5 chocolate hits all Colruyt. Most
    multi-retailer deals UIs interleave so each retailer gets at least one
    early slot, letting the user compare deals across stores at a glance.

    Bucketing rules:
      - Rows with the same `score` (within float epsilon) form a bucket.
      - Within a bucket, group by `source_retailer`, preserving SQL order
        (which is promo_depth DESC, validity_end ASC after the tiebreaker
        change). Iterate retailers in the order their first row appeared
        in the bucket — so the retailer holding the bucket's top item
        leads the round.
      - Round-robin: round 1 takes each retailer's #1, round 2 each #2,
        etc. Stop when we've collected `limit` items.
      - Across buckets we preserve score-DESC ordering, so a less-relevant
        retailer never jumps a more-relevant one.
    """
    if not rows or limit <= 0:
        return rows[:limit]

    EPS = 1e-9

    out: list[dict[str, Any]] = []
    bucket: list[dict[str, Any]] = [rows[0]]
    bucket_score = float(rows[0].get("score") or 0)

    def flush(b: list[dict[str, Any]]) -> bool:
        """Round-robin a single bucket into `out`. Returns True if `limit`
        is reached and the caller should stop.
        """
        by_retailer: dict[str, list[dict[str, Any]]] = {}
        for r in b:
            by_retailer.setdefault(r.get("source_retailer") or "", []).append(r)
        retailers = list(by_retailer.keys())
        while any(by_retailer[r] for r in retailers):
            for r in retailers:
                if by_retailer[r]:
                    out.append(by_retailer[r].pop(0))
                    if len(out) >= limit:
                        return True
        return False

    for row in rows[1:]:
        s = float(row.get("score") or 0)
        if abs(s - bucket_score) <= EPS:
            bucket.append(row)
        else:
            if flush(bucket):
                return out[:limit]
            bucket = [row]
            bucket_score = s
    flush(bucket)
    return out[:limit]


class PromoItemRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, promo_id: str) -> Optional[PromoItem]:
        result = await self.db.execute(
            select(PromoItem).where(PromoItem.id == promo_id)
        )
        return result.scalar_one_or_none()

    async def get_similar_candidates(
        self,
        *,
        source_id: str,
        source_brand: Optional[str],
        source_category: str,
        source_retailer: str,
        source_display_name: str,
        source_promo_price: float,
        affinity_categories: Sequence[str],
        today: date,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Pull ranked candidate rows for the similarity tier-ranker.

        One round-trip. All four branches of the WHERE are indexed:
          - normalized_brand (btree)
          - granular_category (btree)
          - display_name (gin_trgm_ops)
        Rows returned as plain dicts (not ORM objects) since the service
        layer only needs scalar fields for scoring + projection.
        """
        # Explicit ::text casts on bind params let asyncpg infer parameter
        # types — without them, nullable text params surface
        # "could not determine data type of parameter $N".
        sql = text(
            """
            SELECT
                id,
                display_name,
                display_mechanism,
                display_description,
                display_savings_label,
                display_unit_price,
                mechanism_kind,
                mechanism_x,
                mechanism_y,
                promo_campaign,
                unit_price_value,
                unit_price_unit,
                unit_price_quality,
                pack_size_value,
                pack_size_unit,
                pack_count,
                normalized_brand,
                display_brand,
                primary_brand,
                additional_brands,
                original_price,
                promo_price,
                stated_savings,
                savings_amount,
                min_purchase_qty,
                promo_depth,
                granular_category,
                category,
                source_retailer,
                page_number,
                promo_folder_url,
                validity_start,
                validity_end,
                thumbnail_url,
                image_url,
                hero_url,
                promo_text_markdown,
                is_coupon,
                coupon_type,
                coupon_barcode_value,
                coupon_barcode_format,
                coupon_value,
                coupon_min_purchase,
                coupon_validity_end,
                barcode_bbox_x_min,
                barcode_bbox_y_min,
                barcode_bbox_x_max,
                barcode_bbox_y_max,
                (normalized_brand IS NOT NULL
                 AND CAST(:src_brand AS text) IS NOT NULL
                 AND normalized_brand = CAST(:src_brand AS text))     AS is_same_brand,
                (granular_category = CAST(:src_cat AS text))          AS is_same_category,
                (granular_category = ANY(CAST(:affinity_cats AS text[]))) AS is_affinity,
                (source_retailer <> CAST(:src_retailer AS text))      AS is_cross_store,
                similarity(display_name, CAST(:src_name AS text))     AS name_sim
            FROM promo_items
            WHERE validity_start <= :today
              AND validity_end >= :today
              AND id <> CAST(:src_id AS text)
              AND (
                    (CAST(:src_brand AS text) IS NOT NULL
                     AND normalized_brand = CAST(:src_brand AS text))
                 OR granular_category = CAST(:src_cat AS text)
                 OR granular_category = ANY(CAST(:affinity_cats AS text[]))
                 OR similarity(display_name, CAST(:src_name AS text)) > 0.3
              )
            ORDER BY (
                (CASE WHEN normalized_brand IS NOT NULL
                       AND CAST(:src_brand AS text) IS NOT NULL
                       AND normalized_brand = CAST(:src_brand AS text) THEN 4 ELSE 0 END)
              + (CASE WHEN granular_category = CAST(:src_cat AS text) THEN 2 ELSE 0 END)
              + (CASE WHEN granular_category = ANY(CAST(:affinity_cats AS text[])) THEN 1 ELSE 0 END)
              + similarity(display_name, CAST(:src_name AS text))
            ) DESC
            LIMIT :lim
            """
        )
        params = {
            "src_id": source_id,
            "src_brand": (source_brand or None),
            "src_cat": source_category,
            "src_retailer": source_retailer,
            "src_name": source_display_name,
            "affinity_cats": list(affinity_categories) or [""],
            "today": today,
            "lim": limit,
        }
        result = await self.db.execute(sql, params)
        return [dict(row) for row in result.mappings().all()]

    async def search_active(
        self,
        *,
        query: str,
        today: date,
        matched_categories: Sequence[str] = (),
        store_filter: Optional[Sequence[str]] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search active promos using stacked match paths, ranked in one query.

        Paths:
          1. Trigram similarity on display_name_norm / display_brand_norm /
             search_text_norm / generic_product_type_norm. The _norm columns
             are STORED generated columns (f_unaccent(lower(...))) — ingest
             pays the normalization cost once at write, and every search
             reads pre-normalized values. This lets the GIN trgm indexes
             (which are built on the same expression) actually be used by
             the planner; the previous form wrapping each column in
             `unaccent(lower(...))` per-row defeated index matching.
          2. Prefix ILIKE / word-anchored regex bonuses on the same
             _norm columns.
          3. Category-synonym membership: items whose granular_category is in
             matched_categories get a baseline score so 'bier' surfaces
             Stella Artois etc. that the trigram path alone would miss.

        Returns plain dicts (not ORM objects) — service layer projects to
        PromoStoreItem.
        """
        # Trigram similarity falls off sharply for short queries (a 4-char "coke"
        # against a 50-char blob can score ~0.10 even though "coke" is right there).
        # We complement trigrams with word-anchored regex bonuses so exact-word
        # matches always rank above pure category-synonym matches. The `\m`
        # anchor is critical: a plain `%cola%` substring would also fire on
        # "rucola" and "chocolade", which is the source of the filler items
        # users were seeing at the bottom of the list.
        #
        # The query computes each similarity / regex predicate exactly once
        # in the inner CTE and reuses those values in both the threshold
        # filter and the GREATEST(...) score expression. Without this dedup
        # the planner re-evaluates similarity() up to twice per column per
        # row (once in WHERE, once in SELECT).
        sql = text(
            r"""
            WITH q AS (
                SELECT
                    f_unaccent(lower(CAST(:q AS text))) AS norm,
                    f_unaccent(lower(CAST(:q_re AS text))) AS norm_re
            ),
            candidates AS (
                SELECT
                    -- Only the columns we actually return. Avoids dragging
                    -- p.* (~60 cols, including big TEXT blobs) through the
                    -- CTE materialization.
                    p.id, p.display_name, p.display_mechanism, p.display_description,
                    p.display_savings_label, p.display_unit_price,
                    p.mechanism_kind, p.mechanism_x, p.mechanism_y, p.promo_campaign,
                    p.unit_price_value, p.unit_price_unit, p.unit_price_quality,
                    p.pack_size_value, p.pack_size_unit, p.pack_count,
                    p.normalized_brand, p.display_brand, p.primary_brand, p.additional_brands,
                    p.original_price, p.promo_price, p.stated_savings, p.savings_amount,
                    p.min_purchase_qty, p.promo_depth,
                    p.granular_category, p.category, p.source_retailer,
                    p.page_number, p.promo_folder_url, p.validity_start, p.validity_end,
                    p.thumbnail_url, p.image_url, p.hero_url, p.promo_text_markdown,
                    p.is_coupon, p.coupon_type, p.coupon_barcode_value, p.coupon_barcode_format,
                    p.coupon_value, p.coupon_min_purchase, p.coupon_validity_end,
                    p.barcode_bbox_x_min, p.barcode_bbox_y_min,
                    p.barcode_bbox_x_max, p.barcode_bbox_y_max,
                    -- Compute every similarity / regex / prefix predicate once.
                    similarity(p.display_name_norm, q.norm)         AS sim_name,
                    similarity(p.display_brand_norm, q.norm)        AS sim_brand,
                    similarity(p.search_text_norm, q.norm)          AS sim_text,
                    similarity(p.generic_product_type_norm, q.norm) AS sim_type,
                    (p.display_name_norm LIKE q.norm || '%')        AS prefix_hit,
                    (p.display_name_norm ~ ('\m' || q.norm_re))     AS name_word_hit,
                    (p.search_text_norm ~ ('\m' || q.norm_re))      AS text_word_hit,
                    (p.display_brand_norm ~ ('\m' || q.norm_re))    AS brand_word_hit,
                    (p.generic_product_type_norm ~ ('\m' || q.norm_re)) AS type_word_hit,
                    (cardinality(CAST(:matched_cats AS text[])) > 0
                     AND p.granular_category = ANY(CAST(:matched_cats AS text[]))) AS cat_hit,
                    -- Per-row quality signal in [0, 1]. Used to multiplicatively
                    -- scale the category-floor below so category-synonym matches
                    -- (e.g. "cote dor" → all chocolate items) don't all collapse
                    -- to the same flat 0.5. Each component is bounded; weights
                    -- sum to 1.0:
                    --   discount depth  (40%): 50%+ off saturates the slot
                    --   folder freshness (30%): linear decay over 14 days
                    --   has hero image  (15%): richer rendering
                    --   has any price    (15%): excludes "Prijs in winkel" tiles
                    LEAST(1.0,
                        0.40 * LEAST(coalesce(p.promo_depth, 0) / 50.0, 1.0)
                      + 0.30 * GREATEST(0, 1.0 - (:today - p.validity_start) / 14.0)
                      + 0.15 * CASE WHEN p.hero_url IS NOT NULL AND p.hero_url <> '' THEN 1 ELSE 0 END
                      + 0.15 * CASE WHEN coalesce(p.promo_price, 0) > 0
                                      OR coalesce(p.original_price, 0) > 0 THEN 1 ELSE 0 END
                    ) AS quality
                FROM promo_items p, q
                WHERE p.validity_start <= :today
                  AND p.validity_end >= :today
                  AND (
                        CAST(:stores AS text[]) IS NULL
                     OR cardinality(CAST(:stores AS text[])) = 0
                     OR p.source_retailer = ANY(CAST(:stores AS text[]))
                  )
                  AND (
                        similarity(p.display_name_norm, q.norm) > 0.20
                     OR similarity(p.display_brand_norm, q.norm) > 0.50
                     OR similarity(p.search_text_norm, q.norm) > 0.18
                     OR similarity(p.generic_product_type_norm, q.norm) > 0.50
                     OR p.display_name_norm ~ ('\m' || q.norm_re)
                     OR p.search_text_norm ~ ('\m' || q.norm_re)
                     OR p.display_brand_norm ~ ('\m' || q.norm_re)
                     OR p.generic_product_type_norm ~ ('\m' || q.norm_re)
                     OR (
                            cardinality(CAST(:matched_cats AS text[])) > 0
                            AND p.granular_category = ANY(CAST(:matched_cats AS text[]))
                        )
                  )
            ),
            scored AS (
                SELECT
                    c.*,
                    GREATEST(
                        sim_name,
                        sim_brand * 0.9,
                        sim_text * 0.85,
                        sim_type * 0.8,
                        -- Multiplicative floor: scales with per-row quality so
                        -- two category-synonym hits in the same category no
                        -- longer tie at exactly 0.5. Cap at 0.5 (when quality=1)
                        -- so the category path can't outrank a real name match.
                        CASE WHEN cat_hit THEN 0.5 * quality ELSE 0 END
                    )
                    + CASE WHEN prefix_hit THEN 0.35 ELSE 0 END
                    + CASE WHEN name_word_hit AND NOT prefix_hit THEN 0.25 ELSE 0 END
                    + CASE WHEN text_word_hit THEN 0.20 ELSE 0 END
                    + CASE WHEN brand_word_hit THEN 0.25 ELSE 0 END
                    AS score
                FROM candidates c
            )
            SELECT
                id, display_name, display_mechanism, display_description,
                display_savings_label, display_unit_price,
                mechanism_kind, mechanism_x, mechanism_y, promo_campaign,
                unit_price_value, unit_price_unit, unit_price_quality,
                pack_size_value, pack_size_unit, pack_count,
                normalized_brand, display_brand, primary_brand, additional_brands,
                original_price, promo_price, stated_savings, savings_amount,
                min_purchase_qty, promo_depth,
                granular_category, category, source_retailer,
                page_number, promo_folder_url, validity_start, validity_end,
                thumbnail_url, image_url, hero_url, promo_text_markdown,
                is_coupon, coupon_type, coupon_barcode_value, coupon_barcode_format,
                coupon_value, coupon_min_purchase, coupon_validity_end,
                barcode_bbox_x_min, barcode_bbox_y_min,
                barcode_bbox_x_max, barcode_bbox_y_max,
                score
            FROM scored
            WHERE score > 0.3
            ORDER BY score DESC, promo_depth DESC NULLS LAST, validity_end ASC
            LIMIT :lim
            """
        )
        # Pull a wider candidate pool than the user asked for so the Python
        # store-interleaving pass below has rows from multiple retailers to
        # round-robin through within each score-tied bucket. Capped so a
        # large `limit` doesn't balloon the per-row work.
        fetch_limit = min(max(limit * 3, limit + 20), 80)
        params = {
            "q": query,
            "q_re": re.escape(query),
            "today": today,
            "matched_cats": list(matched_categories),
            "stores": list(store_filter) if store_filter else None,
            "lim": fetch_limit,
        }
        result = await self.db.execute(sql, params)
        rows = [dict(row) for row in result.mappings().all()]
        return _interleave_by_store(rows, limit)

    async def popular_brands(
        self, today: date, limit: int = 10
    ) -> list[tuple[str, int]]:
        """Top display_brand values among currently-active promos."""
        sql = text(
            """
            SELECT display_brand, COUNT(*) AS n
            FROM promo_items
            WHERE validity_start <= :today
              AND validity_end >= :today
              AND display_brand IS NOT NULL
              AND display_brand <> ''
            GROUP BY display_brand
            ORDER BY n DESC, display_brand ASC
            LIMIT :lim
            """
        )
        result = await self.db.execute(sql, {"today": today, "lim": limit})
        return [(row[0], row[1]) for row in result.all()]

    async def get_active(
        self, today: date, retailer: Optional[str] = None
    ) -> list[PromoItem]:
        stmt = select(PromoItem).where(
            PromoItem.validity_start <= today,
            PromoItem.validity_end >= today,
        )
        if retailer:
            stmt = stmt.where(PromoItem.source_retailer == retailer)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_active_by_category(
        self, today: date, granular_category: str
    ) -> list[PromoItem]:
        result = await self.db.execute(
            select(PromoItem).where(
                PromoItem.validity_start <= today,
                PromoItem.validity_end >= today,
                PromoItem.granular_category == granular_category,
            )
        )
        return list(result.scalars().all())

    async def upsert_batch(self, items: list[dict]) -> int:
        if not items:
            return 0
        stmt = insert(PromoItem).values(items)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "display_name": stmt.excluded.display_name,
                "display_name_lower": stmt.excluded.display_name_lower,
                "display_mechanism": stmt.excluded.display_mechanism,
                "display_description": stmt.excluded.display_description,
                "display_savings_label": stmt.excluded.display_savings_label,
                "display_unit_price": stmt.excluded.display_unit_price,
                "unit_price_value": stmt.excluded.unit_price_value,
                "unit_price_unit": stmt.excluded.unit_price_unit,
                "unit_price_quality": stmt.excluded.unit_price_quality,
                "pack_size_value": stmt.excluded.pack_size_value,
                "pack_size_unit": stmt.excluded.pack_size_unit,
                "pack_count": stmt.excluded.pack_count,
                "original_price": stmt.excluded.original_price,
                "promo_price": stmt.excluded.promo_price,
                "savings_amount": stmt.excluded.savings_amount,
                "min_purchase_qty": stmt.excluded.min_purchase_qty,
                "promo_depth": stmt.excluded.promo_depth,
                "granular_category": stmt.excluded.granular_category,
                "source_retailer": stmt.excluded.source_retailer,
                "source_type": stmt.excluded.source_type,
                "page_number": stmt.excluded.page_number,
                "promo_folder_url": stmt.excluded.promo_folder_url,
                "validity_start": stmt.excluded.validity_start,
                "validity_end": stmt.excluded.validity_end,
                "thumbnail_url": stmt.excluded.thumbnail_url,
                "image_url": stmt.excluded.image_url,
                "hero_url": stmt.excluded.hero_url,
                "promo_text_markdown": stmt.excluded.promo_text_markdown,
                "search_text": stmt.excluded.search_text,
                "generic_product_type": stmt.excluded.generic_product_type,
                "is_coupon": stmt.excluded.is_coupon,
                "coupon_type": stmt.excluded.coupon_type,
                "coupon_barcode_value": stmt.excluded.coupon_barcode_value,
                "coupon_barcode_format": stmt.excluded.coupon_barcode_format,
                "coupon_value": stmt.excluded.coupon_value,
                "coupon_min_purchase": stmt.excluded.coupon_min_purchase,
                "coupon_validity_end": stmt.excluded.coupon_validity_end,
                "barcode_bbox_x_min": stmt.excluded.barcode_bbox_x_min,
                "barcode_bbox_y_min": stmt.excluded.barcode_bbox_y_min,
                "barcode_bbox_x_max": stmt.excluded.barcode_bbox_x_max,
                "barcode_bbox_y_max": stmt.excluded.barcode_bbox_y_max,
            },
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount

    async def delete_by_retailer_validity(
        self, retailer: str, validity_start: date, validity_end: date
    ) -> int:
        result = await self.db.execute(
            delete(PromoItem).where(
                PromoItem.source_retailer == retailer,
                PromoItem.validity_start == validity_start,
                PromoItem.validity_end == validity_end,
            )
        )
        await self.db.flush()
        return result.rowcount

    async def delete_by_retailer(self, retailer: str) -> int:
        result = await self.db.execute(
            delete(PromoItem).where(PromoItem.source_retailer == retailer)
        )
        await self.db.flush()
        return result.rowcount

    async def delete_all(self) -> int:
        result = await self.db.execute(delete(PromoItem))
        await self.db.flush()
        return result.rowcount

    async def count_active(self, today: date) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(PromoItem).where(
                PromoItem.validity_start <= today,
                PromoItem.validity_end >= today,
            )
        )
        return result.scalar_one()

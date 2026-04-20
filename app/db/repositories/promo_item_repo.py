from datetime import date
from typing import Any, Optional, Sequence

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.promo_item import PromoItem


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
                unit_price_value,
                unit_price_unit,
                unit_price_quality,
                pack_size_value,
                pack_size_unit,
                pack_count,
                normalized_brand,
                display_brand,
                original_price,
                promo_price,
                savings_amount,
                min_purchase_qty,
                promo_depth,
                granular_category,
                source_retailer,
                page_number,
                promo_folder_url,
                validity_start,
                validity_end,
                thumbnail_url,
                image_url,
                (normalized_brand IS NOT NULL
                 AND CAST(:src_brand AS text) IS NOT NULL
                 AND normalized_brand = CAST(:src_brand AS text))     AS is_same_brand,
                (granular_category = CAST(:src_cat AS text))          AS is_same_category,
                (granular_category = ANY(CAST(:affinity_cats AS text[]))) AS is_affinity,
                (source_retailer <> CAST(:src_retailer AS text))      AS is_cross_store,
                similarity(display_name, CAST(:src_name AS text))     AS name_sim
            FROM promo_items
            WHERE validity_end >= :today
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

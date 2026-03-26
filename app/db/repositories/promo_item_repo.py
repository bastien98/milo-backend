from datetime import date
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.promo_item import PromoItem


class PromoItemRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

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

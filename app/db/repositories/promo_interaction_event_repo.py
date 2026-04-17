from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.promo_interaction_event import PromoInteractionEvent


class PromoInteractionEventRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        event_type: str,
        user_id: Optional[str] = None,
        promo_item_id: Optional[str] = None,
        source_item_id: Optional[str] = None,
        store_name: Optional[str] = None,
        metadata_json: Optional[Any] = None,
    ) -> PromoInteractionEvent:
        event = PromoInteractionEvent(
            user_id=user_id,
            event_type=event_type,
            promo_item_id=promo_item_id,
            source_item_id=source_item_id,
            store_name=store_name,
            metadata_json=metadata_json,
        )
        self.db.add(event)
        await self.db.flush()
        return event

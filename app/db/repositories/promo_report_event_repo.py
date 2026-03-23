from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PromoReportEventType
from app.models.promo_report_event import PromoReportEvent


class PromoReportEventRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        report_id: str,
        user_id: str,
        event_type: PromoReportEventType,
        item_key: Optional[str] = None,
        store_name: Optional[str] = None,
        metadata_json: Optional[Any] = None,
    ) -> PromoReportEvent:
        event = PromoReportEvent(
            report_id=report_id,
            user_id=user_id,
            event_type=event_type,
            item_key=item_key,
            store_name=store_name,
            metadata_json=metadata_json,
        )
        self.db.add(event)
        await self.db.flush()
        await self.db.refresh(event)
        return event

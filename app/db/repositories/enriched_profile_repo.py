from datetime import datetime, date
from typing import Optional, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_enriched_profile import UserEnrichedProfile


class EnrichedProfileRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_user_id(self, user_id: str) -> Optional[UserEnrichedProfile]:
        result = await self.db.execute(
            select(UserEnrichedProfile).where(UserEnrichedProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        user_id: str,
        shopping_habits: Any,
        promo_interest_items: Any,
        data_period_start: Optional[date],
        data_period_end: Optional[date],
        receipts_analyzed: int,
    ) -> UserEnrichedProfile:
        profile = await self.get_by_user_id(user_id)

        if profile is None:
            profile = UserEnrichedProfile(
                user_id=user_id,
                shopping_habits=shopping_habits,
                promo_interest_items=promo_interest_items,
                data_period_start=data_period_start,
                data_period_end=data_period_end,
                receipts_analyzed=receipts_analyzed,
                last_rebuilt_at=datetime.now(),
            )
            self.db.add(profile)
        else:
            profile.shopping_habits = shopping_habits
            profile.promo_interest_items = promo_interest_items
            profile.data_period_start = data_period_start
            profile.data_period_end = data_period_end
            profile.receipts_analyzed = receipts_analyzed
            profile.last_rebuilt_at = datetime.now()

        await self.db.flush()
        await self.db.refresh(profile)
        return profile

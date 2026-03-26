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

    async def list_user_ids(self) -> list[str]:
        result = await self.db.execute(select(UserEnrichedProfile.user_id))
        return [row[0] for row in result.all()]

    async def upsert(
        self,
        user_id: str,
        shopping_habits: Any,
        category_profiles: Optional[Any] = None,
        data_period_start: Optional[date] = None,
        data_period_end: Optional[date] = None,
        receipts_analyzed: int = 0,
    ) -> UserEnrichedProfile:
        profile = await self.get_by_user_id(user_id)

        if profile is None:
            profile = UserEnrichedProfile(
                user_id=user_id,
                shopping_habits=shopping_habits,
                category_profiles=category_profiles,
                data_period_start=data_period_start,
                data_period_end=data_period_end,
                receipts_analyzed=receipts_analyzed,
                last_rebuilt_at=datetime.now(),
            )
            self.db.add(profile)
        else:
            profile.shopping_habits = shopping_habits
            profile.category_profiles = category_profiles
            profile.data_period_start = data_period_start
            profile.data_period_end = data_period_end
            profile.receipts_analyzed = receipts_analyzed
            profile.last_rebuilt_at = datetime.now()

        await self.db.flush()
        await self.db.refresh(profile)
        return profile

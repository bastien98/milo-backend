from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.promo_candidates import PromoCandidates


class PromoCandidatesRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_user(self, user_id: str) -> Optional[PromoCandidates]:
        result = await self.db.execute(
            select(PromoCandidates).where(
                PromoCandidates.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_for_user(
        self, candidates_id: str, user_id: str
    ) -> Optional[PromoCandidates]:
        result = await self.db.execute(
            select(PromoCandidates).where(
                PromoCandidates.id == candidates_id,
                PromoCandidates.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        candidates_id: str,
        user_id: str,
        report_date: date,
        generated_at: datetime,
        candidates_json: Any,
        closing_nudge: str,
        smart_switch_json: Optional[Any],
        store_tips_json: Optional[Any],
        interest_item_count: int,
        total_matches: int,
        existing: Optional[PromoCandidates] = None,
    ) -> PromoCandidates:
        if existing is None:
            existing = await self.get_by_user(user_id)
        if existing is None:
            candidates = PromoCandidates(
                id=candidates_id,
                user_id=user_id,
                report_date=report_date,
                generated_at=generated_at,
                candidates_json=candidates_json,
                closing_nudge=closing_nudge,
                smart_switch_json=smart_switch_json,
                store_tips_json=store_tips_json,
                interest_item_count=interest_item_count,
                total_matches=total_matches,
            )
            self.db.add(candidates)
        else:
            existing.generated_at = generated_at
            existing.report_date = report_date
            existing.candidates_json = candidates_json
            existing.closing_nudge = closing_nudge
            existing.smart_switch_json = smart_switch_json
            existing.store_tips_json = store_tips_json
            existing.interest_item_count = interest_item_count
            existing.total_matches = total_matches
            candidates = existing

        await self.db.flush()
        await self.db.refresh(candidates)
        return candidates

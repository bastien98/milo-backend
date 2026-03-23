import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.promo_reports import BRUSSELS_TZ, current_brussels_date
from app.db.repositories.promo_candidates_repo import PromoCandidatesRepository
from scripts.promo_reports.promo_candidate_generation import PromoCandidateGenerationService


class PromoCandidateGenerator:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.candidates_repo = PromoCandidatesRepository(db)
        self.generation_service = PromoCandidateGenerationService(db)

    async def generate_candidates(
        self,
        user_id: str,
        report_date: Optional[date] = None,
    ):
        """Generate and store the candidate pool for a user, always replacing existing.

        Returns (PromoCandidates, was_created).
        """
        report_date = report_date or current_brussels_date()

        existing = await self.candidates_repo.get_by_user(user_id)
        generated_at = datetime.now(BRUSSELS_TZ)
        result = await self.generation_service.build_candidates(
            user_id,
            report_date=report_date,
        )

        candidates_id = existing.id if existing is not None else str(uuid.uuid4())

        if result is None:
            candidates = await self.candidates_repo.upsert(
                candidates_id=candidates_id,
                user_id=user_id,
                report_date=report_date,
                generated_at=generated_at,
                candidates_json=[],
                closing_nudge="",
                smart_switch_json=[],
                store_tips_json={},
                interest_item_count=0,
                total_matches=0,
                existing=existing,
            )
        else:
            candidates = await self.candidates_repo.upsert(
                candidates_id=candidates_id,
                user_id=user_id,
                report_date=report_date,
                generated_at=generated_at,
                candidates_json=result["candidates"],
                closing_nudge="",
                smart_switch_json=[],
                store_tips_json={},
                interest_item_count=result["interest_item_count"],
                total_matches=result["total_matches"],
                existing=existing,
            )

        return candidates, True

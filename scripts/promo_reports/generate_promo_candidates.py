"""Generate promo candidate pools for all users with enriched profiles.

Usage:
  python -m scripts.promo_reports.generate_promo_candidates
"""

import asyncio
import logging
import sys

from app.core.promo_reports import current_brussels_date
from app.db.repositories.enriched_profile_repo import EnrichedProfileRepository
from app.db.session import async_session_maker
from scripts.promo_reports.promo_candidate_generator import PromoCandidateGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def generate_candidates_for_users() -> None:
    report_date = current_brussels_date()

    async with async_session_maker() as session:
        enriched_repo = EnrichedProfileRepository(session)
        user_ids = await enriched_repo.list_user_ids()

    logger.info(
        "Generating promo candidates for %s (report_date) across %s users",
        report_date,
        len(user_ids),
    )

    created = 0
    failed = 0
    sem = asyncio.Semaphore(5)

    async def _process_user(current_user_id: str) -> str:
        async with sem:
            async with async_session_maker() as session:
                generator = PromoCandidateGenerator(session)
                try:
                    await generator.generate_candidates(
                        current_user_id,
                        report_date=report_date,
                    )
                    await session.commit()
                    logger.info("Generated promo candidates for user %s", current_user_id)
                    return "created"
                except Exception:
                    await session.rollback()
                    logger.exception("Failed to generate promo candidates for user %s", current_user_id)
                    return "failed"

    results = await asyncio.gather(*[_process_user(uid) for uid in user_ids])
    created = results.count("created")
    failed = results.count("failed")

    logger.info(
        "Done: %s generated, %s failed",
        created,
        failed,
    )


async def _main() -> None:
    await generate_candidates_for_users()


if __name__ == "__main__":
    asyncio.run(_main())

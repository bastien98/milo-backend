"""
Daily cron job: rebuild enriched profiles for all active users.

Intended to run as a Railway cron service at 3 AM UTC daily.
Usage:  python -m scripts.rebuild_profiles
"""

import asyncio
import logging
import sys
from datetime import date, timedelta

from sqlalchemy import select, func

from app.db.session import async_session_maker
from app.models.transaction import Transaction
from app.services.enriched_profile_service import EnrichedProfileService, LOOKBACK_DAYS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def rebuild_all_profiles() -> None:
    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)

    async with async_session_maker() as session:
        # Find all users with transactions in the lookback window
        result = await session.execute(
            select(Transaction.user_id)
            .where(Transaction.date >= cutoff)
            .group_by(Transaction.user_id)
        )
        user_ids = [row[0] for row in result.all()]

    logger.info(f"Found {len(user_ids)} users with activity since {cutoff}")

    succeeded = 0
    failed = 0

    for user_id in user_ids:
        async with async_session_maker() as session:
            try:
                await EnrichedProfileService.rebuild_profile(user_id, session)
                await session.commit()
                succeeded += 1
                logger.info(f"Rebuilt profile for user {user_id}")
            except Exception:
                logger.exception(f"Failed to rebuild profile for user {user_id}")
                await session.rollback()
                failed += 1

    logger.info(
        f"Done: {succeeded} profiles rebuilt, {failed} failures "
        f"out of {len(user_ids)} users"
    )


if __name__ == "__main__":
    asyncio.run(rebuild_all_profiles())

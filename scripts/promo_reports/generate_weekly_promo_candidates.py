"""Generate weekly promo candidate pools for all users with enriched profiles.

Usage:
  python -m scripts.promo_reports.generate_weekly_promo_candidates
  python -m scripts.promo_reports.generate_weekly_promo_candidates --week 2026-W12
  python -m scripts.promo_reports.generate_weekly_promo_candidates --replace-existing
"""

import argparse
import asyncio
import logging
import sys
from datetime import date

from app.core.promo_reports import compute_promo_week, current_brussels_date
from app.db.repositories.enriched_profile_repo import EnrichedProfileRepository
from app.db.session import async_session_maker
from scripts.promo_reports.weekly_promo_candidate_generator import WeeklyPromoCandidateGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _parse_week(week_str: str) -> date:
    iso_year_str, iso_week_str = week_str.split("-W", 1)
    iso_year = int(iso_year_str)
    iso_week = int(iso_week_str)
    return date.fromisocalendar(iso_year, iso_week, 1)


async def generate_candidates_for_users(
    *,
    report_date: date,
    replace_existing: bool,
) -> None:
    async with async_session_maker() as session:
        enriched_repo = EnrichedProfileRepository(session)
        user_ids = await enriched_repo.list_user_ids()

    week = compute_promo_week(report_date)
    logger.info(
        "Generating promo candidates for ISO week %s-W%s (%s to %s) across %s users",
        week["iso_year"],
        str(week["iso_week"]).zfill(2),
        week["start"],
        week["end"],
        len(user_ids),
    )

    created = 0
    skipped = 0
    failed = 0
    sem = asyncio.Semaphore(5)

    async def _process_user(current_user_id: str) -> str:
        async with sem:
            async with async_session_maker() as session:
                generator = WeeklyPromoCandidateGenerator(session)
                try:
                    _, was_created = await generator.generate_weekly_candidates(
                        current_user_id,
                        report_date=report_date,
                        replace_existing=replace_existing,
                    )
                    await session.commit()
                    if was_created:
                        logger.info("Generated weekly promo candidates for user %s", current_user_id)
                        return "created"
                    else:
                        logger.info("Skipped existing weekly promo candidates for user %s", current_user_id)
                        return "skipped"
                except Exception:
                    await session.rollback()
                    logger.exception("Failed to generate weekly promo candidates for user %s", current_user_id)
                    return "failed"

    results = await asyncio.gather(*[_process_user(uid) for uid in user_ids])
    created = results.count("created")
    skipped = results.count("skipped")
    failed = results.count("failed")

    logger.info(
        "Done: %s generated, %s skipped, %s failed",
        created,
        skipped,
        failed,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate weekly promo candidate pools.")
    parser.add_argument(
        "--week",
        help="ISO week in the format YYYY-Www. Defaults to the current Europe/Brussels week.",
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Replace existing candidates for the target week instead of skipping them.",
    )
    return parser


async def _main() -> None:
    args = _build_parser().parse_args()
    report_date = _parse_week(args.week) if args.week else current_brussels_date()
    await generate_candidates_for_users(
        report_date=report_date,
        replace_existing=args.replace_existing,
    )


if __name__ == "__main__":
    asyncio.run(_main())

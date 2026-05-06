"""
One-shot: regenerate every brand-cashback campaign thumbnail.

Pulls each campaign's hero from S3, runs the current `_make_thumb` (fit-and-pad
to a 1:1 square with THUMB_PAD_RGB), uploads to the existing thumb key. Use
this after changing the thumbnail strategy or pad color so legacy thumbs
stop showing the old crop.

Usage:  python -m scripts.regenerate_brand_cashback_thumbs
"""

import asyncio
import logging
import sys

from sqlalchemy import select

from app.api.v2.brand_cashback import _decode_image, _make_thumb
from app.db.session import async_session_maker
from app.models.brand_cashback import BrandCashbackCampaign
from app.services.brand_cashback_service import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def regenerate_all_thumbs() -> None:
    if not storage.enabled:
        logger.error("Storage is not enabled (BUCKET_NAME empty). Aborting.")
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(BrandCashbackCampaign).where(
                BrandCashbackCampaign.image_s3_key.is_not(None),
                BrandCashbackCampaign.image_thumb_s3_key.is_not(None),
            )
        )
        campaigns = result.scalars().all()

    logger.info(f"Found {len(campaigns)} campaigns with hero + thumb keys")

    succeeded = 0
    failed = 0

    for campaign in campaigns:
        try:
            hero_bytes = storage.download(campaign.image_s3_key)
            if not hero_bytes:
                logger.warning(f"[{campaign.id}] hero download returned empty; skipping")
                failed += 1
                continue

            decoded = _decode_image(hero_bytes)
            thumb_bytes = _make_thumb(decoded)

            storage.upload_campaign_image(
                campaign.id, thumb_bytes, "jpg", variant="thumb"
            )
            succeeded += 1
            logger.info(f"[{campaign.id}] regenerated thumb ({len(thumb_bytes)} bytes)")
        except Exception as e:
            failed += 1
            logger.error(f"[{campaign.id}] failed: {e}")

    logger.info(f"Done: {succeeded} succeeded, {failed} failed")


if __name__ == "__main__":
    asyncio.run(regenerate_all_thumbs())

"""End-to-end classifier test.

Hits the live promopromo.be listing for each retailer, downloads each folder's
cover image, and runs the Gemini classifier. Asserts that at least one folder
per retailer passes (or falls through the fail-open path if Gemini is unreachable).

Skipped automatically when GEMINI_API_KEY is not set — so it won't run in CI
unless credentials are provided.
"""

from __future__ import annotations

import logging
import os

import pytest

from promo_folders_pipelines.scraper.classify import (
    ClassificationUnavailable,
    is_grocery_folder,
    select_food_folders,
)
from promo_folders_pipelines.scraper.config import RETAILERS
from promo_folders_pipelines.scraper.scrape import discover_folders, download_cover_image

logger = logging.getLogger(__name__)


pytestmark = pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set; skipping live classifier e2e",
)


@pytest.mark.parametrize("retailer_key", list(RETAILERS.keys()))
def test_classifier_picks_grocery_folder(retailer_key: str):
    """For every retailer, select_food_folders must yield at least one folder.

    This covers the path we broke in production: Colruyt had 2 active folders
    and classification returned 0 (rate limit + name-filter mismatch), leaving
    the cron with nothing to ingest.
    """
    cfg = RETAILERS[retailer_key]
    folders = discover_folders(cfg["shop_slug"], cfg["shop_uuid"])
    assert folders, f"No live folders advertised for {retailer_key} — promopromo.be may be down"

    selected = select_food_folders(
        folders,
        max_folders=cfg["max_folders"],
        retailer_name=cfg["store_id"],
    )

    assert selected, (
        f"Classifier selected 0 folders for {retailer_key}. "
        f"Candidates were: {[(f.name, f.uuid) for f in folders]}"
    )
    assert len(selected) <= cfg["max_folders"], "Selected more than max_folders"


def test_explicit_yes_on_colruyt_cover():
    """Direct call: classify a live Colruyt folder cover. Must come back YES
    (or raise ClassificationUnavailable on persistent rate-limit — that's the
    acceptable failure mode)."""
    cfg = RETAILERS["colruyt"]
    folders = discover_folders(cfg["shop_slug"], cfg["shop_uuid"])
    assert folders, "No Colruyt folders available on promopromo.be"

    folder = folders[0]
    cover = download_cover_image(folder)
    try:
        decision = is_grocery_folder(cover, cfg["store_id"])
    except ClassificationUnavailable as e:
        pytest.skip(f"Gemini classifier unavailable (this is handled by fail-open): {e}")
    else:
        assert decision is True, (
            f"Colruyt folder {folder.name!r} ({folder.uuid}) was classified NO — "
            "prompt may need tightening"
        )

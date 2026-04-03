#!/usr/bin/env python3
"""
Unified daily pipeline: scrape promopromo.be → extract via Gemini → upsert to PostgreSQL.

Single cron job that handles the full promo folder lifecycle:
1. Discover active folders from promopromo.be
2. Classify folders (Gemini Vision filter for food/grocery)
3. Detect changes (compare folder UUIDs against R2 metadata)
4. Download new folder page images
5. Upload to Cloudflare R2
6. Extract promo items via Gemini (expensive — only for new folders)
7. Upsert to PostgreSQL
8. Regenerate promo candidates for users

Usage (from milo-backend/):
    # Run for all retailers
    python -m promo_folders_pipelines.scraper.daily_pipeline

    # Single retailer
    python -m promo_folders_pipelines.scraper.daily_pipeline --store colruyt

    # Dry run (discover + detect changes only)
    python -m promo_folders_pipelines.scraper.daily_pipeline --dry-run

    # Force reprocess (bypass change detection)
    python -m promo_folders_pipelines.scraper.daily_pipeline --force

    # Target specific database
    python -m promo_folders_pipelines.scraper.daily_pipeline --env non-prod
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure backend root is on sys.path
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_ROOT / ".env")
except ImportError:
    print("ERROR: python-dotenv not installed.")
    sys.exit(1)

from promo_folders_pipelines.r2_storage import R2PromoStorage
from promo_folders_pipelines.pipeline import (
    extract_promos_from_images,
    parse_promo_items,
    upsert_to_postgres,
    delete_retailer_promos_pg,
)
from promo_folders_pipelines.stores import load_store_config
from promo_folders_pipelines.scraper.config import get_retailer, list_retailers
from promo_folders_pipelines.scraper.scrape import (
    discover_folders,
    download_cover_image,
    download_page_images,
    fetch_folder_pages,
    FolderInfo,
)
from promo_folders_pipelines.scraper.classify import classify_folder
from promo_folders_pipelines.scraper.upload import (
    clear_store,
    upload_folder,
    get_existing_folder_uuids,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


def _select_folders(
    key: str, config: dict, folders: list[FolderInfo],
) -> list[FolderInfo]:
    """Classify and filter folders for a retailer."""
    max_folders = config["max_folders"]

    # Name-based filter (e.g. Colruyt → only "Alle Acties" folder)
    name_filter = config.get("folder_name_filter")
    if name_filter:
        matched = [f for f in folders if name_filter.lower() in f.name.lower()]
        if matched:
            logger.info(f"Name filter '{name_filter}': matched {len(matched)}/{len(folders)} folder(s)")
            return matched[:max_folders]
        else:
            logger.warning(f"Name filter '{name_filter}' matched 0/{len(folders)} folders, falling back to classification")

    if len(folders) == 1:
        logger.info("Single folder found, skipping classification")
        return folders

    selected = []
    for folder in folders:
        try:
            cover = download_cover_image(folder)
            is_food = classify_folder(cover, config["store_id"])
            if is_food:
                selected.append(folder)
                if len(selected) >= max_folders:
                    logger.info(f"Reached max_folders={max_folders}, stopping classification")
                    break
        except Exception as e:
            logger.warning(f"Classification failed for {folder.uuid}: {e}")
            continue

    logger.info(
        f"Classification: {len(selected)}/{len(folders)} folders accepted as food/grocery"
    )
    return selected


def process_retailer(
    key: str,
    r2: R2PromoStorage,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """Run the full pipeline for one retailer.

    Returns a dict with: store_id, folders_found, folders_new, items_extracted, items_upserted.
    """
    config = get_retailer(key)
    store_id = config["store_id"]
    shop_slug = config["shop_slug"]
    shop_uuid = config["shop_uuid"]

    logger.info(f"{'=' * 60}")
    logger.info(f"Processing {key} (store_id='{store_id}')")
    logger.info(f"{'=' * 60}")

    result = {
        "store_id": store_id,
        "folders_found": 0,
        "folders_new": 0,
        "items_extracted": 0,
        "items_upserted": 0,
    }

    # Step 1: Discover folders
    folders = discover_folders(shop_slug, shop_uuid)
    result["folders_found"] = len(folders)
    if not folders:
        logger.warning(f"No folders found for {key}")
        return result

    # Step 2: Classify
    selected = _select_folders(key, config, folders)
    if not selected:
        logger.warning(f"No food/grocery folders found for {key}")
        return result

    # Step 3: Change detection
    if force:
        new_folders = selected
        logger.info(f"Force mode: processing all {len(selected)} folder(s)")
    else:
        existing_uuids = get_existing_folder_uuids(r2, store_id)
        new_folders = [f for f in selected if f.uuid not in existing_uuids]
        unchanged = len(selected) - len(new_folders)
        if unchanged:
            logger.info(f"Change detection: {unchanged} folder(s) unchanged, {len(new_folders)} new")

    result["folders_new"] = len(new_folders)

    if not new_folders:
        logger.info(f"No new folders for {key}, skipping extraction")
        return result

    if dry_run:
        logger.info(f"[DRY RUN] Would process {len(new_folders)} new folder(s):")
        for i, f in enumerate(new_folders, 1):
            logger.info(f"  folder_{i}: {f.name} ({f.uuid}) {f.validity_start} - {f.validity_end}")
        return result

    # Step 4: Clear R2 and re-upload ALL selected folders (keeps R2 in sync)
    clear_store(r2, store_id)

    all_items = []
    store_config = load_store_config(key)
    canonical_store_id = store_config["store_id"]

    for idx, folder in enumerate(selected, 1):
        logger.info(f"--- Folder {idx}/{len(selected)}: {folder.uuid} ---")

        # Download page images
        folder_pages = fetch_folder_pages(folder)
        if not folder_pages.pages:
            logger.warning(f"No pages found for folder {folder.uuid}, skipping")
            continue

        page_images = download_page_images(folder_pages)

        # Upload to R2
        upload_folder(r2, store_id, idx, folder_pages, page_images)

        # Only extract via Gemini if this folder is NEW
        if folder.uuid not in [f.uuid for f in new_folders]:
            logger.info(f"Folder {folder.uuid} unchanged, skipping Gemini extraction")
            continue

        # Step 5: Gemini extraction
        logger.info(f"Extracting promo items via Gemini ({len(page_images)} pages)...")
        raw_data = extract_promos_from_images(page_images, store_config)

        # Inject validity dates from scraper metadata (more reliable than Gemini inference)
        if not raw_data.get("validity_start"):
            raw_data["validity_start"] = folder.validity_start
        if not raw_data.get("validity_end"):
            raw_data["validity_end"] = folder.validity_end

        # Step 6: Parse & validate
        source_url = f"https://www.promopromo.be/nl/{folder.shop_slug}-folder/{folder.uuid}/0"
        items = parse_promo_items(raw_data, canonical_store_id, source_url)
        all_items.extend(items)
        result["items_extracted"] += len(items)

    # Step 7: Delete old promos and upsert new ones
    if all_items:
        # Group items by validity window for scoped deletion
        seen_windows = set()
        for item in all_items:
            window = (item.validity_start, item.validity_end)
            if window not in seen_windows and window[0] and window[1]:
                seen_windows.add(window)
                delete_retailer_promos_pg(canonical_store_id, window[0], window[1])

        upserted = upsert_to_postgres(all_items)
        result["items_upserted"] = upserted

    logger.info(
        f"Done: {key} — {result['folders_new']} new folder(s), "
        f"{result['items_extracted']} items extracted, {result['items_upserted']} upserted"
    )
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Daily promo folder pipeline: scrape → extract → upsert."
    )
    parser.add_argument("--store", help="Single retailer key (e.g., 'colruyt')")
    parser.add_argument("--all", action="store_true", help="Process all retailers (default if no --store)")
    parser.add_argument("--dry-run", action="store_true", help="Discover + detect changes only, no extraction/upload")
    parser.add_argument("--force", action="store_true", help="Bypass change detection, reprocess everything")
    parser.add_argument(
        "--env",
        choices=["prod", "non-prod"],
        default="non-prod",
        help="Target database environment (default: non-prod)",
    )
    parser.add_argument(
        "--skip-candidates",
        action="store_true",
        help="Skip promo candidate regeneration after ingestion",
    )
    args = parser.parse_args()

    # Environment override
    if args.env == "prod":
        logger.info("Targeting PRODUCTION database")
    else:
        nonprod_url = os.environ.get("DATABASE_URL_NONPROD", "")
        if not nonprod_url:
            parser.error("DATABASE_URL_NONPROD not set in .env")
        os.environ["DATABASE_URL"] = nonprod_url
        logger.info("Targeting NON-PROD database")

    # Determine retailers to process
    if args.store:
        keys = [args.store]
    else:
        keys = list_retailers()

    r2 = R2PromoStorage()

    success_count = 0
    fail_count = 0
    total_new = 0
    total_items = 0

    for key in keys:
        try:
            result = process_retailer(key, r2, dry_run=args.dry_run, force=args.force)
            total_new += result["folders_new"]
            total_items += result["items_upserted"]
            success_count += 1
        except Exception as e:
            logger.error(f"Failed to process {key}: {e}", exc_info=True)
            fail_count += 1

    # Summary
    logger.info(f"\n{'=' * 60}")
    logger.info(f"PIPELINE SUMMARY")
    logger.info(f"  Retailers: {success_count} succeeded, {fail_count} failed")
    logger.info(f"  New folders processed: {total_new}")
    logger.info(f"  Items upserted: {total_items}")
    logger.info(f"{'=' * 60}")

    # Regenerate promo candidates (only if we upserted new items)
    if total_items > 0 and not args.dry_run and not args.skip_candidates:
        logger.info("Regenerating promo candidates for all users...")
        import asyncio
        from scripts.promo_reports.generate_promo_candidates import generate_candidates_for_users
        try:
            asyncio.run(generate_candidates_for_users())
            logger.info("Promo candidate regeneration complete")
        except Exception as e:
            logger.error(f"Promo candidate regeneration failed: {e}", exc_info=True)

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

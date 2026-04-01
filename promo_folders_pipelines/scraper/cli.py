#!/usr/bin/env python3
"""
CLI entry point for the promopromo.be promo folder scraper.

Scrapes promotional folder images from promopromo.be and uploads them
to Cloudflare R2. Uses Gemini Vision to filter for food/grocery folders.

Usage (from milo-backend/):
    # Scrape one retailer
    python -m promo_folders_pipelines.scraper.cli --store albert_heijn

    # Scrape all retailers
    python -m promo_folders_pipelines.scraper.cli --all

    # Dry run (discover + classify, don't download/upload)
    python -m promo_folders_pipelines.scraper.cli --store colruyt --dry-run

    # List available retailers
    python -m promo_folders_pipelines.scraper.cli --list-stores
"""

import argparse
import logging
import sys
from pathlib import Path

# Ensure backend root is on sys.path
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_ROOT / ".env")
except ImportError:
    print("ERROR: python-dotenv not installed. Run with the venv Python:")
    print("  .venv/bin/python -m promo_folders_pipelines.scraper.cli ...")
    sys.exit(1)

from promo_folders_pipelines.scraper.config import get_retailer, list_retailers
from promo_folders_pipelines.scraper.scrape import (
    discover_folders,
    download_cover_image,
    download_page_images,
    fetch_folder_pages,
)
from promo_folders_pipelines.scraper.classify import classify_folder
from promo_folders_pipelines.scraper.upload import clear_store, upload_folder

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


def scrape_retailer(key: str, dry_run: bool = False) -> bool:
    """Run the full scrape pipeline for one retailer.

    Returns True if at least one folder was successfully processed.
    """
    config = get_retailer(key)
    store_id = config["store_id"]
    shop_slug = config["shop_slug"]
    shop_uuid = config["shop_uuid"]
    max_folders = config["max_folders"]

    logger.info(f"=== Scraping {key} (store_id='{store_id}') ===")

    # Step 1: Discover active folders
    folders = discover_folders(shop_slug, shop_uuid)
    if not folders:
        logger.warning(f"No folders found for {key}")
        return False

    # Step 2: Classify folders with Gemini Vision
    # Always classify when multiple folders exist to filter non-food folders.
    # Skip classification only for single-folder retailers.
    if len(folders) == 1:
        selected = folders
        logger.info("Single folder found, skipping classification")
    else:
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
            f"Classification: {len(selected)}/{len(folders)} folders accepted as food/grocery "
            f"(max_folders={max_folders})"
        )

    if not selected:
        logger.warning(f"No food/grocery folders found for {key}")
        return False

    if dry_run:
        logger.info(f"[DRY RUN] Would process {len(selected)} folder(s):")
        for i, f in enumerate(selected, 1):
            logger.info(f"  folder_{i}: {f.name} ({f.uuid}) {f.validity_start} - {f.validity_end}")
        return True

    # Step 3: Download page images for each selected folder
    from promo_folders_pipelines.r2_storage import R2PromoStorage
    r2 = R2PromoStorage()

    # Step 4: Clear existing data (idempotent)
    clear_store(r2, store_id)

    # Step 5: Process each folder
    total_pages = 0
    for idx, folder in enumerate(selected, 1):
        logger.info(f"--- Processing folder {idx}/{len(selected)}: {folder.uuid} ---")

        # Fetch page image URLs
        folder_pages = fetch_folder_pages(folder)
        if not folder_pages.pages:
            logger.warning(f"No pages found for folder {folder.uuid}, skipping")
            continue

        # Download all page images
        page_images = download_page_images(folder_pages)

        # Upload to R2
        upload_folder(r2, store_id, idx, folder_pages, page_images)
        total_pages += len(page_images)

    logger.info(
        f"=== Done: {key} — {len(selected)} folder(s), {total_pages} total pages ==="
    )
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Scrape promo folders from promopromo.be and upload to Cloudflare R2."
    )
    parser.add_argument(
        "--store",
        help="Retailer key (e.g., 'albert_heijn', 'colruyt')",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Scrape all configured retailers",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and classify only; don't download images or upload to R2",
    )
    parser.add_argument(
        "--list-stores",
        action="store_true",
        help="List all available retailer keys and exit",
    )
    args = parser.parse_args()

    if args.list_stores:
        retailers = list_retailers()
        print(f"Available retailers ({len(retailers)}):")
        for r in retailers:
            config = get_retailer(r)
            print(f"  {r:20s} → store_id='{config['store_id']}', max_folders={config['max_folders']}")
        sys.exit(0)

    if not args.store and not args.all:
        parser.error("--store or --all is required (use --list-stores to see options)")

    if args.all:
        keys = list_retailers()
    else:
        keys = [args.store]

    success_count = 0
    fail_count = 0

    for key in keys:
        try:
            ok = scrape_retailer(key, dry_run=args.dry_run)
            if ok:
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            logger.error(f"Failed to scrape {key}: {e}", exc_info=True)
            fail_count += 1

    if len(keys) > 1:
        logger.info(f"Summary: {success_count} succeeded, {fail_count} failed")

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

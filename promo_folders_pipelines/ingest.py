#!/usr/bin/env python3
"""
Promo folder ingestion CLI — reads PDFs from Cloudflare R2, upserts to PostgreSQL.

Usage (from milo-backend/):
    # Ingest a specific week (production)
    python3 -m promo_folders_pipelines.ingest --store colruyt --week 2026-W13

    # Ingest to non-prod
    python3 -m promo_folders_pipelines.ingest --store colruyt --week 2026-W13 --env non-prod

    # Ingest all weeks for a store
    python3 -m promo_folders_pipelines.ingest --store colruyt

    # Dry-run (extract only, no database upsert)
    python3 -m promo_folders_pipelines.ingest --store colruyt --dry-run

    # List available stores
    python3 -m promo_folders_pipelines.ingest --list-stores
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Ensure backend root is on sys.path so we can import from app.*
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_ROOT / ".env")
except ImportError:
    print("ERROR: python-dotenv not installed. Run with the venv Python:")
    print(f"  .venv/bin/python -m promo_folders_pipelines.ingest ...")
    sys.exit(1)

from promo_folders_pipelines.cache_refresh import notify_folders_cache_refresh
from promo_folders_pipelines.stores import list_stores, load_store_config
from promo_folders_pipelines.pipeline import (
    delete_expired_promos_pg,
    delete_retailer_promos_pg,
    run_pipeline,
)
from promo_folders_pipelines.r2_storage import R2PromoStorage

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


def _confirm(prompt: str) -> bool:
    """Ask the user for confirmation. Returns True only if they type 'yes'."""
    response = input(f"\n⚠️  {prompt}\n   Type 'yes' to confirm: ").strip().lower()
    return response == "yes"


def _check_duplicate_pdfs(
    r2: R2PromoStorage,
    store_id: str,
    target_week: str,
    pdf_refs: list[dict],
) -> None:
    """Check if any target week PDFs already exist in the last 3 other weeks.

    Uses HEAD requests (ETags) — no PDF bytes are downloaded.
    Prompts for confirmation if duplicates are found.
    """
    # Get ETags for target week's PDFs
    target_etags = {}
    for ref in pdf_refs:
        etag = r2.get_pdf_etag(store_id, target_week, ref["filename"])
        target_etags[ref["filename"]] = etag

    # Get last 3 other weeks (excluding target)
    all_weeks = r2.list_store_weeks(store_id)
    other_weeks = [w for w in all_weeks if w != target_week][-3:]

    if not other_weeks:
        return

    # HEAD each PDF in other weeks, compare ETags
    duplicates = []
    for week in other_weeks:
        for pdf in r2.list_week_pdfs(store_id, week):
            etag = r2.get_pdf_etag(store_id, week, pdf)
            for target_file, target_etag in target_etags.items():
                if etag == target_etag:
                    duplicates.append((target_file, target_week, pdf, week))

    if duplicates:
        for t_file, t_week, o_file, o_week in duplicates:
            logger.warning(
                f"Duplicate PDF detected: {store_id}/{t_week}/{t_file} "
                f"has same content as {store_id}/{o_week}/{o_file}"
            )
        if not _confirm("Duplicate PDF(s) detected. Continue anyway?"):
            sys.exit(1)


def _collect_pdfs_from_r2(
    r2: R2PromoStorage,
    store_id: str,
    week: str | None = None,
) -> list[dict]:
    """Collect PDF references from R2 with their metadata.

    Returns a list of dicts with keys: store_id, week, filename, metadata.
    Aborts if any PDF is missing a metadata entry.
    """
    if week:
        weeks = [week]
    else:
        weeks = r2.list_store_weeks(store_id)
        if not weeks:
            logger.error(f"No promo folders found in R2 for store '{store_id}'")
            sys.exit(1)
        logger.info(f"Found {len(weeks)} week(s) for '{store_id}': {weeks}")

    pdf_refs = []

    for w in weeks:
        metadata = r2.download_metadata(store_id, w)
        if metadata is None:
            logger.error(
                f"No metadata.json found in R2 for {store_id}/{w}/. "
                f"Every week directory must have a metadata.json file."
            )
            sys.exit(1)

        pdfs = r2.list_week_pdfs(store_id, w)
        if not pdfs:
            logger.warning(f"No PDFs found in {store_id}/{w}/, skipping")
            continue

        for pdf in pdfs:
            if pdf not in metadata:
                logger.error(
                    f"PDF '{pdf}' has no entry in {store_id}/{w}/metadata.json. "
                    f"Every PDF must have a metadata entry with validity dates."
                )
                sys.exit(1)

            if not metadata[pdf].get("promo_folder_url"):
                logger.error(
                    f"PDF '{pdf}' in {store_id}/{w}/metadata.json is missing "
                    f"'promo_folder_url'. Every PDF entry must carry the per-folder "
                    f"promopromo URL (matching the folder's R2 metadata.json source_url) "
                    f"so hotspots can be scoped to the correct folder."
                )
                sys.exit(1)

            pdf_refs.append({
                "store_id": store_id,
                "week": w,
                "filename": pdf,
                "metadata": metadata[pdf],
            })

    return pdf_refs


def main():
    parser = argparse.ArgumentParser(
        description="Ingest promo folder PDFs from Cloudflare R2 into the PostgreSQL promo_items table."
    )
    parser.add_argument(
        "--store",
        help="Store ID (canonical name from stores.py, e.g. 'colruyt', 'delhaize')",
    )
    parser.add_argument(
        "--week",
        help="Specific week directory to ingest (e.g. '2026-W12'). Requires --store.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract and parse only; do not upsert to database",
    )
    parser.add_argument(
        "--env",
        choices=["prod", "non-prod"],
        default="non-prod",
        help="Target environment: 'non-prod' (default) or 'prod'",
    )
    parser.add_argument(
        "--list-stores",
        action="store_true",
        help="List all available store configs and exit",
    )
    parser.add_argument(
        "--output",
        help="Path to write extracted items as JSON (defaults to ./extracted_promos.json in dry-run mode)",
    )
    parser.add_argument(
        "--page",
        type=int,
        help=(
            "1-indexed page number to re-extract in isolation. Scopes extraction and the "
            "pre-ingest delete to just this page; other pages of the same folder are untouched. "
            "Only valid when exactly one PDF will be processed (requires --store + --week, and "
            "that week must resolve to a single PDF)."
        ),
    )
    args = parser.parse_args()

    # --- Environment override ---
    if args.env == "prod":
        logger.info("Targeting PRODUCTION database")
    else:
        nonprod_url = os.environ.get("DATABASE_URL_NONPROD", "")
        if not nonprod_url:
            parser.error("DATABASE_URL_NONPROD not set in .env")
        os.environ["DATABASE_URL"] = nonprod_url
        logger.info("Targeting NON-PROD database")

    # --- List stores ---
    if args.list_stores:
        stores = list_stores()
        print(f"Available stores ({len(stores)}):")
        for s in stores:
            print(f"  - {s}")
        sys.exit(0)

    # --- Validate argument combinations ---
    if args.week and not args.store:
        parser.error("--week requires --store")
    if args.page is not None and not args.week:
        parser.error("--page requires --week (and --store) so it resolves to a single folder")
    if args.page is not None and args.page < 1:
        parser.error("--page must be >= 1")

    # --- Full ingestion pipeline ---
    if not args.store:
        parser.error("--store is required (use --list-stores to see available stores)")

    # DB hygiene: drop rows whose validity window is already in the past. Safe to
    # run every invocation; expired rows are already hidden from the API by
    # query-time filters, this just prevents unbounded table growth.
    if not args.dry_run:
        from datetime import date
        delete_expired_promos_pg(date.today())

    # Collect PDFs from R2
    r2 = R2PromoStorage()
    pdf_refs = _collect_pdfs_from_r2(r2, args.store, args.week)

    if not pdf_refs:
        logger.error("No PDFs to ingest.")
        sys.exit(1)

    if args.page is not None and len(pdf_refs) != 1:
        parser.error(
            f"--page {args.page} requires exactly one PDF but {len(pdf_refs)} resolved from "
            f"store '{args.store}' week '{args.week}'. Narrow the week or remove --page."
        )

    logger.info(f"Will ingest {len(pdf_refs)} PDF(s) for store '{args.store}'")

    # Duplicate check: compare ETags against last 3 other weeks
    if args.week and args.page is None:
        _check_duplicate_pdfs(r2, args.store, args.week, pdf_refs)

    # Clean slate: delete existing promos before ingesting (idempotent)
    if not args.dry_run:
        canonical = load_store_config(args.store)["store_id"]
        if args.page is not None:
            # Page-scoped delete: only this single page of this single folder.
            ref = pdf_refs[0]
            meta = ref["metadata"]
            delete_retailer_promos_pg(
                canonical,
                validity_start=meta.get("validity_start"),
                validity_end=meta.get("validity_end"),
                page_number=args.page,
                promo_folder_url=meta.get("promo_folder_url"),
            )
        elif args.week:
            # Scoped delete: only this week's validity windows
            seen_windows = set()
            for ref in pdf_refs:
                meta = ref["metadata"]
                window = (meta.get("validity_start"), meta.get("validity_end"))
                if window not in seen_windows and window[0] and window[1]:
                    seen_windows.add(window)
                    delete_retailer_promos_pg(canonical, validity_start=window[0], validity_end=window[1])
        else:
            # Full delete: all weeks for this retailer
            delete_retailer_promos_pg(canonical)

    # Ingest each PDF (auto_delete=False since we already cleaned up above)
    all_items = []
    for idx, ref in enumerate(pdf_refs):
        label = f"{ref['store_id']}/{ref['week']}/{ref['filename']}"
        meta = ref["metadata"]

        if len(pdf_refs) > 1:
            logger.info(f"--- [{idx + 1}/{len(pdf_refs)}] {label} ---")

        # Download PDF from R2
        pdf_data = r2.download_pdf(ref["store_id"], ref["week"], ref["filename"])

        items = run_pipeline(
            store_id=args.store,
            pdf_data=pdf_data,
            promo_folder_url=meta["promo_folder_url"],
            dry_run=args.dry_run,
            pdf_label=label,
            validity_start=meta.get("validity_start"),
            validity_end=meta.get("validity_end"),
            page_filter=args.page,
        )
        all_items.extend(items)

    if len(pdf_refs) > 1:
        logger.info(f"Total: {len(all_items)} items from {len(pdf_refs)} PDFs")

    # Write results to JSON
    output_path = args.output
    if not output_path and args.dry_run:
        output_path = "extracted_promos.json"

    if output_path and all_items:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(
                [
                    {
                        "display_name": i.display_name,
                        "display_mechanism": i.display_mechanism,
                        "display_description": i.display_description,
                        "display_savings_label": i.display_savings_label,
                        "display_unit_price": i.display_unit_price,
                        "unit_price_value": i.unit_price_value,
                        "unit_price_unit": i.unit_price_unit,
                        "unit_price_quality": i.unit_price_quality,
                        "pack_size_value": i.pack_size_value,
                        "pack_size_unit": i.pack_size_unit,
                        "pack_count": i.pack_count,
                        "original_price": i.original_price,
                        "promo_price": i.promo_price,
                        "savings_amount": i.savings_amount,
                        "granular_category": i.granular_category,
                        "parent_category": i.parent_category,
                        "validity_start": i.validity_start,
                        "validity_end": i.validity_end,
                        "page_number": i.page_number,
                        "promo_folder_url": i.promo_folder_url,
                    }
                    for i in all_items
                ],
                f,
                indent=2,
                ensure_ascii=False,
            )
        logger.info(f"Wrote {len(all_items)} items to {output_path}")

        # Sibling QA JSON — one entry per folder_url so the report is diffable
        # across re-runs and across model versions.
        from collections import defaultdict as _defaultdict
        from promo_folders_pipelines.qa_report import anomalies_to_json, detect_anomalies

        by_folder: dict[str, list] = _defaultdict(list)
        for item in all_items:
            by_folder[item.promo_folder_url or ""].append(item)

        qa_payload = [
            {
                "promo_folder_url": folder_url,
                "total_items": len(folder_items),
                "anomalies": anomalies_to_json(detect_anomalies(folder_items)),
            }
            for folder_url, folder_items in by_folder.items()
        ]
        qa_path = output_path.with_suffix(output_path.suffix + ".qa.json")
        with open(qa_path, "w") as f:
            json.dump(qa_payload, f, indent=2, ensure_ascii=False)
        logger.info(f"Wrote QA anomaly report to {qa_path}")

    # Drop the API's folders cache so the new hotspots show up immediately.
    if not args.dry_run and all_items:
        notify_folders_cache_refresh(args.env)


if __name__ == "__main__":
    main()

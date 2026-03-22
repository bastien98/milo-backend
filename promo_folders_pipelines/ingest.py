#!/usr/bin/env python3
"""
Promo folder ingestion CLI — reads PDFs from Cloudflare R2.

Usage (from milo-backend/):
    # Ingest all promo folders for a store (all weeks)
    python -m promo_folders_pipelines.ingest --store colruyt

    # Ingest a specific week
    python -m promo_folders_pipelines.ingest --store colruyt --week 2026-W12

    # Dry-run (extract only, no Pinecone upsert)
    python -m promo_folders_pipelines.ingest --store colruyt --dry-run

    # Delete all promos for a store
    python -m promo_folders_pipelines.ingest --clear-index --store colruyt

    # Delete entire promos index
    python -m promo_folders_pipelines.ingest --nuke-index

    # List available stores
    python -m promo_folders_pipelines.ingest --list-stores
"""

import argparse
import json
import logging
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

from promo_folders_pipelines.stores import list_stores, load_store_config
from promo_folders_pipelines.pipeline import run_pipeline, clear_all_retailer_promos, nuke_entire_index
from promo_folders_pipelines.r2_storage import R2PromoStorage

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


def _confirm(prompt: str) -> bool:
    """Ask the user for confirmation. Returns True only if they type 'yes'."""
    response = input(f"\n⚠️  {prompt}\n   Type 'yes' to confirm: ").strip().lower()
    return response == "yes"


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

            pdf_refs.append({
                "store_id": store_id,
                "week": w,
                "filename": pdf,
                "metadata": metadata[pdf],
            })

    return pdf_refs


def main():
    parser = argparse.ArgumentParser(
        description="Ingest promo folder PDFs from Cloudflare R2 into the Pinecone promos index."
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
        help="Extract and parse only; do not upsert to Pinecone",
    )
    parser.add_argument(
        "--clear-index",
        action="store_true",
        help="Clear ALL existing promos for this store (requires confirmation)",
    )
    parser.add_argument(
        "--nuke-index",
        action="store_true",
        help="Delete ALL records from the entire promos index (requires confirmation)",
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
    args = parser.parse_args()

    # --- List stores ---
    if args.list_stores:
        stores = list_stores()
        print(f"Available stores ({len(stores)}):")
        for s in stores:
            print(f"  - {s}")
        sys.exit(0)

    # --- Nuke entire index (standalone command) ---
    if args.nuke_index:
        if not _confirm(
            "This will DELETE ALL records from the entire Pinecone promos index.\n"
            "   This affects ALL stores, ALL validity periods. This cannot be undone."
        ):
            logger.info("Aborted.")
            sys.exit(0)
        deleted = nuke_entire_index()
        logger.info(f"Done. {deleted} records deleted from the entire index.")
        sys.exit(0)

    # --- Validate argument combinations ---
    if args.week and not args.store:
        parser.error("--week requires --store")

    # --- Clear store index (standalone, without ingestion) ---
    if args.clear_index and not args.week:
        if not args.store:
            parser.error("--store is required with --clear-index")
        canonical = load_store_config(args.store)["store_id"]
        if not _confirm(
            f"This will DELETE ALL promos for store '{canonical}' from the Pinecone index.\n"
            f"   This cannot be undone."
        ):
            logger.info("Aborted.")
            sys.exit(0)
        deleted = clear_all_retailer_promos(canonical)
        logger.info(f"Done. {deleted} records deleted for store '{canonical}'.")
        sys.exit(0)

    # --- Full ingestion pipeline ---
    if not args.store:
        parser.error("--store is required (use --list-stores to see available stores)")

    # HITL confirmation for --clear-index during ingestion
    if args.clear_index:
        if not _confirm(
            f"This will DELETE ALL existing promos for store '{args.store}' before ingesting.\n"
            f"   This cannot be undone."
        ):
            logger.info("Aborted.")
            sys.exit(0)

    # Collect PDFs from R2
    r2 = R2PromoStorage()
    pdf_refs = _collect_pdfs_from_r2(r2, args.store, args.week)

    if not pdf_refs:
        logger.error("No PDFs to ingest.")
        sys.exit(1)

    logger.info(f"Will ingest {len(pdf_refs)} PDF(s) for store '{args.store}'")

    # Ingest each PDF
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
            promo_folder_url=meta.get("promo_folder_url"),
            dry_run=args.dry_run,
            clear_index=args.clear_index if idx == 0 else False,
            auto_delete=idx == 0,
            pdf_label=label,
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
                        "normalized_name": i.normalized_name,
                        "original_description": i.original_description,
                        "normalized_brand": i.normalized_brand,
                        "is_premium": i.is_premium,
                        "packaging_type": i.packaging_type,
                        "granular_category": i.granular_category,
                        "parent_category": i.parent_category,
                        "original_price": i.original_price,
                        "promo_price": i.promo_price,
                        "promo_mechanism": i.promo_mechanism,
                        "pack_size": i.pack_size,
                        "content_value": i.content_value,
                        "content_unit": i.content_unit,
                        "unit_info": i.unit_info,
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


if __name__ == "__main__":
    main()

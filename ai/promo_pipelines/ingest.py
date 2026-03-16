#!/usr/bin/env python3
"""
Generic promo folder ingestion CLI.

Usage (from milo-backend/):
    python -m ai.promo_pipelines.ingest --store colruyt --folder-path ./folder.pdf
    python -m ai.promo_pipelines.ingest --store delhaize --folder-path ./folder.pdf --url https://...
    python -m ai.promo_pipelines.ingest --store aldi --folder-path ./folder.pdf --dry-run
    python -m ai.promo_pipelines.ingest --list-stores
    python -m ai.promo_pipelines.ingest --clear-index --store colruyt
    python -m ai.promo_pipelines.ingest --nuke-index
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Ensure backend root is on sys.path so we can import from app.*
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_ROOT / ".env")
except ImportError:
    print("ERROR: python-dotenv not installed. Run with the venv Python:")
    print(f"  .venv/bin/python -m ai.promo_pipelines.ingest ...")
    sys.exit(1)

from ai.promo_pipelines.stores import list_stores
from ai.promo_pipelines.pipeline import run_pipeline, clear_all_retailer_promos, nuke_entire_index

PROMO_FOLDERS_DIR = Path(__file__).resolve().parent / "promo_folders"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


def _confirm(prompt: str) -> bool:
    """Ask the user for confirmation. Returns True only if they type 'yes'."""
    response = input(f"\n⚠️  {prompt}\n   Type 'yes' to confirm: ").strip().lower()
    return response == "yes"


def _find_latest_folder(store_id: str, all_pdfs: bool = False) -> list[Path]:
    """Find PDFs for a store in the most recent week directory.

    Directories are sorted alphabetically (YYYY-W{WW}_... format ensures
    chronological order).

    If all_pdfs=False: returns [folder.pdf] from the latest directory.
    If all_pdfs=True: returns all *.pdf files from the latest directory.
    """
    store_dir = PROMO_FOLDERS_DIR / store_id
    if not store_dir.is_dir():
        logger.error(f"No promo_folders directory for store '{store_id}': {store_dir}")
        sys.exit(1)

    # Find all subdirectories containing at least one PDF
    week_dirs = sorted(
        [d for d in store_dir.iterdir() if d.is_dir() and list(d.glob("*.pdf"))],
        key=lambda d: d.name,
    )
    if not week_dirs:
        logger.error(f"No PDFs found in any subdirectory of {store_dir}")
        sys.exit(1)

    latest_dir = week_dirs[-1]

    if all_pdfs:
        pdfs = sorted(latest_dir.glob("*.pdf"))
        logger.info(f"Found {len(pdfs)} PDF(s) for '{store_id}' in {latest_dir.name}: {[p.name for p in pdfs]}")
        return pdfs
    else:
        main_pdf = latest_dir / "folder.pdf"
        if not main_pdf.exists():
            logger.error(f"No folder.pdf in {latest_dir} — use --all to ingest all PDFs, or rename your PDF to folder.pdf")
            sys.exit(1)
        logger.info(f"Latest folder for '{store_id}': {main_pdf}")
        return [main_pdf]


def main():
    parser = argparse.ArgumentParser(
        description="Ingest a promo folder PDF into the Pinecone promos index."
    )
    parser.add_argument(
        "--store",
        help="Store ID (canonical name from stores.py, e.g. 'colruyt', 'delhaize')",
    )
    parser.add_argument(
        "--folder-path",
        help="Path to the promo folder PDF",
    )
    parser.add_argument(
        "--url",
        help="URL of the promo folder source (stored as metadata)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract and parse only; do not upsert to Pinecone",
    )
    parser.add_argument(
        "--clear-index",
        action="store_true",
        help="Clear ALL existing promos for this store before ingesting (requires confirmation)",
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
        "--latest",
        action="store_true",
        help="Auto-find the most recent folder.pdf in promo_folders/{store}/ (replaces --folder-path)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="With --latest: ingest ALL *.pdf files in the latest week directory (not just folder.pdf)",
    )
    parser.add_argument(
        "--output",
        help="Path to write extracted items as JSON (defaults to stdout in dry-run mode)",
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

    # --- Validate --all requires --latest ---
    if getattr(args, "all") and not args.latest:
        parser.error("--all requires --latest")

    # --- Resolve --latest to PDF path(s) ---
    pdf_paths = []
    if args.latest:
        if args.folder_path:
            parser.error("--latest and --folder-path are mutually exclusive")
        if not args.store:
            parser.error("--store is required with --latest")
        pdf_paths = _find_latest_folder(args.store, all_pdfs=getattr(args, "all"))
    elif args.folder_path:
        pdf_paths = [Path(args.folder_path)]

    # --- Clear store index (standalone, without ingestion) ---
    if args.clear_index and not pdf_paths:
        if not args.store:
            parser.error("--store is required with --clear-index")
        if not _confirm(
            f"This will DELETE ALL promos for store '{args.store}' from the Pinecone index.\n"
            f"   This cannot be undone."
        ):
            logger.info("Aborted.")
            sys.exit(0)
        deleted = clear_all_retailer_promos(args.store)
        logger.info(f"Done. {deleted} records deleted for store '{args.store}'.")
        sys.exit(0)

    # --- Full ingestion pipeline ---
    if not args.store:
        parser.error("--store is required (use --list-stores to see available stores)")
    if not pdf_paths:
        parser.error("--folder-path or --latest is required")

    # HITL confirmation for --clear-index during ingestion
    if args.clear_index:
        if not _confirm(
            f"This will DELETE ALL existing promos for store '{args.store}' before ingesting.\n"
            f"   This cannot be undone."
        ):
            logger.info("Aborted.")
            sys.exit(0)

    # Ingest each PDF (only clear index on the first one)
    all_items = []
    for idx, pdf_path in enumerate(pdf_paths):
        if not pdf_path.exists():
            logger.error(f"PDF not found: {pdf_path}")
            sys.exit(1)

        if len(pdf_paths) > 1:
            logger.info(f"--- Ingesting PDF {idx + 1}/{len(pdf_paths)}: {pdf_path.name} ---")

        items = run_pipeline(
            store_id=args.store,
            pdf_path=pdf_path,
            promo_folder_url=args.url,
            dry_run=args.dry_run,
            clear_index=args.clear_index if idx == 0 else False,
            auto_delete=idx == 0,  # Only auto-delete before the first PDF
        )
        all_items.extend(items)

    if len(pdf_paths) > 1:
        logger.info(f"Total: {len(all_items)} items from {len(pdf_paths)} PDFs")

    # Write results to JSON
    output_path = args.output
    if not output_path and args.dry_run:
        output_path = pdf_paths[0].parent / "extracted_promos.json"

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

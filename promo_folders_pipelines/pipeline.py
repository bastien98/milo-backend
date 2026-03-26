"""
Generic promo folder ingestion pipeline engine.

Shared functions for PDF splitting, Gemini extraction (structured output),
parsing, and PostgreSQL upsert.
"""

import hashlib
import json
import logging
import os
import re
import time
from datetime import date
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF
from google import genai
from google.genai import types
from pydantic import BaseModel as PydanticBaseModel, Field

from app.core.categories import (
    CATEGORIES_PROMPT_LIST,
    GRANULAR_CATEGORIES,
    get_parent_category,
)
from promo_folders_pipelines.models import PromoItem
from promo_folders_pipelines.promo_depth import compute_promo_depth
from promo_folders_pipelines.prompt_builder import build_system_prompt
from promo_folders_pipelines.stores import load_store_config

logger = logging.getLogger(__name__)

# Type alias — pipeline functions accept raw PDF bytes (downloaded from R2)
PdfData = bytes

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

GEMINI_MODEL = "gemini-3-pro-preview"
MAX_OUTPUT_TOKENS = 32768
PAGES_PER_BATCH = 2
MAX_BATCH_BYTES = 1_500_000  # 1.5 MB — split oversized batches into single pages
MAX_RETRIES = 4
RETRY_BASE_DELAY = 5  # seconds, doubles each retry
REQUEST_TIMEOUT = 300  # 5 minutes per Gemini call


# ---------------------------------------------------------------------------
# Pydantic schemas for Gemini structured output
# ---------------------------------------------------------------------------
class _PromoItemSchema(PydanticBaseModel):
    # --- Display fields (all required except display_unit_price) ---
    display_name: str = Field(description="Clean Title Case product label: Brand + product + variant + size. ALWAYS include size/quantity when visible (e.g., '4 x 125 g' not just '125 g'). For drinks, volume is CRITICAL (e.g., '33 cl', '6 x 25 cl', '1,5 L'). No promo text or pricing. Examples: 'Oîkos Yoghurt Appel-Kaneel 4 x 115 g', 'Coca-Cola Zero 1,5 L', 'Jupiler Pils 24 x 25 cl'.")
    display_mechanism: str = Field(description="Standardized promo label. Title case, consistent formatting. For conditional percentage discounts, ALWAYS include the condition (e.g., '-25% Vanaf 2 Verpakkingen', NOT just '-25%'). Only use bare '-25%' if the discount applies to a single item with no minimum purchase. Examples: '1+1 Gratis', '-25%', '-25% Vanaf 2 Verpakkingen', '-20% Vanaf 3 Flessen', '-30% Vanaf 12 Blikken', '2e aan Halve Prijs', '2+1 Gratis', 'Prijsverlaging'.")
    display_description: str = Field(description="Plain-language Dutch explanation of the deal (~80 chars max). Explain what the shopper needs to DO and what they GET. Examples: 'Koop 2 en krijg de 3e gratis', 'Nu €0.80 goedkoper per stuk'. Must be understandable without seeing the folder.")
    display_savings_label: str = Field(description="Human-friendly savings text. Examples: '1 Gratis Item', 'Bespaar €3.00', 'Tot -25% Korting', '2e aan Halve Prijs'.")
    display_unit_price: Optional[str] = Field(default=None, description="Price per standard unit computed from promo_price and size info visible on the page. Use Belgian units: €/L for drinks, €/kg for food, €/stuk for countable items, €/rol for paper products, €/stuk for tea bags/tabs/doekjes. For wine assume 75 cl, for beer blik assume 33 cl. Format: '€X.XX/unit'. null ONLY if no size info whatsoever.")

    # --- Price reasoning (scratchpad — generated before prices to improve accuracy) ---
    price_reasoning: str = Field(description="Show your work: what is the promo mechanism, what prices are visible on the page, and how you calculated promo_price and savings_amount step by step. This field is not displayed to users.")

    # --- Pricing (all required, non-negative) ---
    original_price: float = Field(ge=0, description="Regular price before promo, rounded to 2 decimal places. REQUIRED — skip item if not visible.")
    promo_price: float = Field(ge=0, description="Price of ONE item/pack as shown on shelf. For ANY X+Y gratis deal (1+1, 2+1, 3+3, 4+1, 12+6, etc.): ALWAYS same as original_price. For -25%: original_price × 0.75. For X voor €Y: €Y ÷ X. Rounded to 2 decimal places.")
    savings_amount: float = Field(ge=0, description="Total euro savings when completing the deal. For 1+1 @ €3: savings=3.00. For 2+1 @ €3: savings=3.00. For -25% @ €4: savings=1.00. For 2e halve prijs @ €3: savings=1.50. For 12+6 gratis @ €2.33: savings=13.98. Rounded to 2 decimal places.")

    # --- Purchase quantity (for promo depth calculation) ---
    min_purchase_qty: int = Field(ge=1, description="Minimum number of items/packs a shopper must buy to complete the deal. For 1+1 Gratis: 2. For 2+1 Gratis: 3. For 12+6 Gratis: 18. For 2e aan Halve Prijs: 2. For 2e aan -70%: 2. For -25%: 1. For -25% Vanaf 2 Verpakkingen: 2. For -30% Vanaf 12 Blikken: 12. For Prijsverlaging: 1. For 3 voor €5: 3.")

    # --- Category ---
    granular_category: str = Field(description="Category from the provided list, or 'Other' if nothing fits.")

    # --- Page reference ---
    page_number: int = Field(ge=1, description="Page number within the current PDF batch, 1-indexed.")


class _PromoFolderSchema(PydanticBaseModel):
    validity_start: Optional[date] = Field(default=None, description="Folder validity start date")
    validity_end: Optional[date] = Field(default=None, description="Folder validity end date")
    items: list[_PromoItemSchema] = Field(description="All promotional items extracted")


# ---------------------------------------------------------------------------
# PDF splitting
# ---------------------------------------------------------------------------
def split_pdf_into_batches(
    pdf_data: bytes,
    pages_per_batch: int = PAGES_PER_BATCH,
    max_batch_bytes: int = MAX_BATCH_BYTES,
) -> list[tuple[bytes, int]]:
    """Split a PDF into smaller PDFs of pages_per_batch pages each.

    Returns a list of (batch_bytes, start_page) tuples where start_page is 1-indexed.
    If a batch exceeds max_batch_bytes, it is further split into single-page batches.
    """
    doc = fitz.open(stream=pdf_data, filetype="pdf")
    total_pages = len(doc)
    logger.info(f"PDF has {total_pages} pages, splitting into batches of {pages_per_batch}")

    batches = []
    for start in range(0, total_pages, pages_per_batch):
        end = min(start + pages_per_batch, total_pages)
        batch_doc = fitz.open()
        batch_doc.insert_pdf(doc, from_page=start, to_page=end - 1)
        batch_bytes = batch_doc.tobytes()
        batch_doc.close()

        if len(batch_bytes) > max_batch_bytes and (end - start) > 1:
            # Batch too large — split into single-page batches
            logger.warning(
                f"  Batch pages {start + 1}-{end} is {len(batch_bytes):,} bytes "
                f"(>{max_batch_bytes:,}), splitting into single pages"
            )
            for page_idx in range(start, end):
                single_doc = fitz.open()
                single_doc.insert_pdf(doc, from_page=page_idx, to_page=page_idx)
                batches.append((single_doc.tobytes(), page_idx + 1))
                single_doc.close()
                logger.info(f"  Batch {len(batches)}: page {page_idx + 1}")
        else:
            batches.append((batch_bytes, start + 1))
            logger.info(f"  Batch {len(batches)}: pages {start + 1}-{end} ({len(batch_bytes):,} bytes)")

    doc.close()
    return batches


# ---------------------------------------------------------------------------
# Extraction (structured output mode)
# ---------------------------------------------------------------------------
def extract_batch(
    client: genai.Client,
    batch_pdf: bytes,
    batch_num: int,
    start_page: int,
    system_prompt: str,
    display_name: str,
) -> dict:
    """Extract promo items from a single PDF batch via Gemini structured output."""
    for attempt in range(1, MAX_RETRIES + 1):
        delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
        label = f"[Batch {batch_num}]"

        if attempt == 1:
            logger.info(f"{label} Sending to Gemini ({len(batch_pdf):,} bytes)...")
        else:
            logger.info(f"{label} Retry {attempt}/{MAX_RETRIES} after {delay}s backoff...")
            time.sleep(delay)

        start_time = time.time()

        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=batch_pdf, mime_type="application/pdf"),
                    f"Extract all promotional product offers from these {display_name} promo folder pages.",
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    temperature=0.0,
                    thinking_config=types.ThinkingConfig(thinking_level="high"),
                    response_mime_type="application/json",
                    response_schema=_PromoFolderSchema,
                    media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
                ),
            )
        except Exception as e:
            elapsed = time.time() - start_time
            logger.warning(f"{label} API error after {elapsed:.1f}s: {e}")
            if attempt == MAX_RETRIES:
                raise
            continue

        elapsed = time.time() - start_time
        response_text = response.text
        if not response_text:
            logger.warning(f"{label} Empty response after {elapsed:.1f}s")
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Batch {batch_num} returned empty after {MAX_RETRIES} retries")
            continue

        # Structured output should guarantee valid JSON, but occasionally
        # Gemini returns trailing commas. Strip them before parsing.
        cleaned = re.sub(r',\s*([}\]])', r'\1', response_text)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning(f"{label} JSON parse error: {e}")
            if attempt == MAX_RETRIES:
                raise
            continue

        # Adjust page numbers: batch-relative → actual PDF page
        for item in data.get("items", []):
            batch_page = item.get("page_number")
            if batch_page is not None:
                item["page_number"] = start_page + batch_page - 1

        item_count = len(data.get("items", []))
        logger.info(f"{label} Done in {elapsed:.1f}s — {item_count} items extracted")
        return data

    return {"items": []}


def extract_promos_from_pdf(pdf_data: bytes, config: Dict[str, Any]) -> dict:
    """Split PDF into batches and extract promo items sequentially."""
    batches = split_pdf_into_batches(pdf_data)
    system_prompt = build_system_prompt(config, CATEGORIES_PROMPT_LIST)
    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options={"timeout": REQUEST_TIMEOUT * 1000},  # milliseconds
    )
    display_name = config["display_name"]

    logger.info(f"Processing {len(batches)} batches sequentially...")
    start_time = time.time()

    all_items = []
    validity_start = None
    validity_end = None

    for i, (batch_pdf, start_page) in enumerate(batches):
        data = extract_batch(client, batch_pdf, i + 1, start_page, system_prompt, display_name)
        if data.get("validity_start") and not validity_start:
            validity_start = data["validity_start"]
            validity_end = data.get("validity_end")
        all_items.extend(data.get("items", []))

    elapsed = time.time() - start_time
    logger.info(f"All batches complete in {elapsed:.1f}s — {len(all_items)} total items")

    # Deduplicate by display_name (keep first occurrence)
    seen = set()
    deduped = []
    for item in all_items:
        name = (item.get("display_name") or "").lower().strip()
        if name and name not in seen:
            seen.add(name)
            deduped.append(item)
        elif name in seen:
            logger.debug(f"Dedup: skipping duplicate '{name}'")

    if len(deduped) < len(all_items):
        logger.info(f"Deduplicated: {len(all_items)} → {len(deduped)} items")

    return {
        "validity_start": validity_start,
        "validity_end": validity_end,
        "items": deduped,
    }


# ---------------------------------------------------------------------------
# Parsing & validation
# ---------------------------------------------------------------------------
def parse_promo_items(
    data: dict,
    store_id: str,
    promo_folder_url: Optional[str] = None,
) -> list[PromoItem]:
    """Parse Gemini structured output into validated PromoItem list.

    Enforces a strict quality gate: items missing any mandatory field
    are dropped. Quality over coverage.
    """
    validity_start = data.get("validity_start")
    validity_end = data.get("validity_end")
    if not validity_start or not validity_end:
        raise ValueError("Promo folder extraction is missing validity_start or validity_end")

    items = []
    skipped = 0

    for raw in data.get("items", []):
        display_name = (raw.get("display_name") or "").strip()
        if not display_name:
            logger.warning("Skipping item with empty display_name")
            skipped += 1
            continue

        # Quality gate: all mandatory fields must be present
        original_price = _parse_price(raw.get("original_price"))
        promo_price = _parse_price(raw.get("promo_price"))
        savings_amount = _parse_price(raw.get("savings_amount"))
        display_mechanism = (raw.get("display_mechanism") or "").strip()
        display_description = (raw.get("display_description") or "").strip()
        display_savings_label = (raw.get("display_savings_label") or "").strip()

        if original_price is None or original_price <= 0:
            logger.warning(f"Skipping '{display_name}': missing or invalid original_price")
            skipped += 1
            continue
        if promo_price is None or promo_price <= 0:
            logger.warning(f"Skipping '{display_name}': missing or invalid promo_price")
            skipped += 1
            continue
        if savings_amount is None or savings_amount <= 0:
            logger.warning(f"Skipping '{display_name}': missing or invalid savings_amount")
            skipped += 1
            continue
        if not display_mechanism:
            logger.warning(f"Skipping '{display_name}': missing display_mechanism")
            skipped += 1
            continue
        if not display_description:
            logger.warning(f"Skipping '{display_name}': missing display_description")
            skipped += 1
            continue
        if not display_savings_label:
            logger.warning(f"Skipping '{display_name}': missing display_savings_label")
            skipped += 1
            continue

        # Price validation
        if promo_price > original_price:
            logger.warning(
                f"Skipping '{display_name}': promo_price ({promo_price}) > original_price ({original_price})"
            )
            skipped += 1
            continue

        # Round prices to 2 decimal places
        original_price = round(original_price, 2)
        promo_price = round(promo_price, 2)
        savings_amount = round(savings_amount, 2)

        # Purchase quantity & promo depth
        min_purchase_qty = max(1, int(raw.get("min_purchase_qty", 1)))
        promo_depth = compute_promo_depth(savings_amount, original_price, min_purchase_qty)

        # Category validation
        granular = raw.get("granular_category", "Other")
        if granular not in GRANULAR_CATEGORIES:
            logger.warning(f"Unknown category '{granular}' for '{display_name}', defaulting to 'Other'")
            granular = "Other"
        parent = get_parent_category(granular)

        items.append(
            PromoItem(
                display_name=display_name,
                display_mechanism=display_mechanism,
                display_description=display_description,
                display_savings_label=display_savings_label,
                display_unit_price=(raw.get("display_unit_price") or "").strip() or None,
                original_price=original_price,
                promo_price=promo_price,
                savings_amount=savings_amount,
                min_purchase_qty=min_purchase_qty,
                promo_depth=promo_depth,
                granular_category=granular,
                parent_category=parent,
                validity_start=validity_start,
                validity_end=validity_end,
                source_retailer=store_id,
                source_type="folder",
                page_number=raw.get("page_number"),
                promo_folder_url=promo_folder_url,
            )
        )

    if skipped:
        logger.info(f"Quality gate: skipped {skipped} items that didn't meet minimum requirements")
    logger.info(f"Parsed {len(items)} high-quality promo items")
    return items


def _parse_price(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def generate_record_id(item: PromoItem) -> str:
    """Generate a deterministic ID for a promo item."""
    key = (
        f"{item.source_retailer}:{item.display_name}:"
        f"{item.validity_start}:{item.validity_end}"
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# PostgreSQL upsert
# ---------------------------------------------------------------------------
def _get_pg_connection_string() -> str:
    """Get a plain postgresql:// connection string for psycopg2."""
    db_url = os.environ.get("DATABASE_URL", "")
    # Strip SQLAlchemy driver suffixes if present
    for suffix in ("+asyncpg", "+psycopg2"):
        db_url = db_url.replace(suffix, "")
    return db_url


def upsert_to_postgres(items: list[PromoItem]) -> int:
    """Upsert promo items to PostgreSQL promo_items table.

    Uses raw psycopg2 — no SQLAlchemy ORM, no model imports needed.
    Caller is responsible for cleanup (use delete_retailer_promos_pg before calling).
    """
    if not items:
        logger.warning("No items to upsert to PostgreSQL")
        return 0

    import psycopg2

    conn = psycopg2.connect(_get_pg_connection_string())
    try:
        cur = conn.cursor()
        for item in items:
            record_id = generate_record_id(item)
            cur.execute(
                """
                INSERT INTO promo_items (
                    id, display_name, display_name_lower, display_mechanism,
                    display_description, display_savings_label, display_unit_price,
                    original_price, promo_price, savings_amount, min_purchase_qty, promo_depth,
                    granular_category, source_retailer, source_type,
                    page_number, promo_folder_url, validity_start, validity_end
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    display_name_lower = EXCLUDED.display_name_lower,
                    display_mechanism = EXCLUDED.display_mechanism,
                    display_description = EXCLUDED.display_description,
                    display_savings_label = EXCLUDED.display_savings_label,
                    display_unit_price = EXCLUDED.display_unit_price,
                    original_price = EXCLUDED.original_price,
                    promo_price = EXCLUDED.promo_price,
                    savings_amount = EXCLUDED.savings_amount,
                    min_purchase_qty = EXCLUDED.min_purchase_qty,
                    promo_depth = EXCLUDED.promo_depth,
                    granular_category = EXCLUDED.granular_category,
                    source_retailer = EXCLUDED.source_retailer,
                    source_type = EXCLUDED.source_type,
                    page_number = EXCLUDED.page_number,
                    promo_folder_url = EXCLUDED.promo_folder_url,
                    validity_start = EXCLUDED.validity_start,
                    validity_end = EXCLUDED.validity_end
                """,
                (
                    record_id,
                    item.display_name,
                    item.display_name.lower(),
                    item.display_mechanism,
                    item.display_description,
                    item.display_savings_label,
                    item.display_unit_price,
                    item.original_price,
                    item.promo_price,
                    item.savings_amount,
                    item.min_purchase_qty,
                    item.promo_depth,
                    item.granular_category,
                    item.source_retailer,
                    item.source_type,
                    item.page_number,
                    item.promo_folder_url,
                    item.validity_start,
                    item.validity_end,
                ),
            )

        conn.commit()
        cur.close()
    finally:
        conn.close()

    logger.info(f"PostgreSQL upsert complete: {len(items)} records in promo_items table")
    return len(items)


def delete_retailer_promos_pg(retailer: str, validity_start: str = None, validity_end: str = None) -> int:
    """Delete promo items from PostgreSQL for a retailer (optionally filtered by validity window)."""
    import psycopg2

    conn = psycopg2.connect(_get_pg_connection_string())
    try:
        cur = conn.cursor()
        if validity_start and validity_end:
            cur.execute(
                "DELETE FROM promo_items WHERE source_retailer = %s AND validity_start = %s AND validity_end = %s",
                (retailer, validity_start, validity_end),
            )
        else:
            cur.execute("DELETE FROM promo_items WHERE source_retailer = %s", (retailer,))
        deleted = cur.rowcount
        conn.commit()
        cur.close()
    finally:
        conn.close()

    if deleted:
        logger.info(f"Deleted {deleted} existing records for {retailer}")
    return deleted


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------
def run_pipeline(
    store_id: str,
    pdf_data: bytes,
    promo_folder_url: Optional[str] = None,
    dry_run: bool = False,
    pdf_label: str = "",
) -> list[PromoItem]:
    """Run the full ingestion pipeline for a store.

    Args:
        store_id: Canonical store name from stores.py (e.g. "colruyt")
        pdf_data: Raw PDF bytes (downloaded from R2)
        promo_folder_url: Optional URL of the promo folder source
        dry_run: If True, extract and parse only — no database upsert
        pdf_label: Human-readable label for logging (e.g. "colruyt/2026-W12/food.pdf")

    Returns:
        List of parsed PromoItem objects
    """
    config = load_store_config(store_id)
    canonical_store_id = config["store_id"]
    display_name = config["display_name"]

    logger.info("=" * 60)
    logger.info(f"{display_name} Promo Folder Ingestion Pipeline")
    logger.info("=" * 60)
    logger.info(f"PDF: {pdf_label or '(bytes)'} ({len(pdf_data):,} bytes)")
    logger.info(f"Store: {canonical_store_id} ({display_name})")

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set in environment")

    # Step 1: Extract from PDF via Gemini
    raw_data = extract_promos_from_pdf(pdf_data, config)

    # Step 2: Parse and validate
    items = parse_promo_items(raw_data, canonical_store_id, promo_folder_url)

    if not items:
        logger.warning("No items extracted. Exiting.")
        return []

    # Step 3: Summary
    logger.info(f"\nExtracted {len(items)} high-quality promo items")
    if items[0].validity_start:
        logger.info(f"Validity: {items[0].validity_start} to {items[0].validity_end}")
    logger.info(f"Categories: {len(set(i.granular_category for i in items))} unique")

    for item in items[:5]:
        logger.info(
            f"  - {item.display_name} | {item.display_mechanism} | "
            f"€{item.promo_price:.2f} (save €{item.savings_amount:.2f})"
        )
    if len(items) > 5:
        logger.info(f"  ... and {len(items) - 5} more")

    # Step 4: Upsert or dry-run
    if dry_run:
        logger.info("DRY RUN — skipping upsert")
    else:
        pg_count = upsert_to_postgres(items)
        logger.info(f"Done! {pg_count} promo records in promo_items table")

    return items

"""
Generic promo folder ingestion pipeline engine.

Shared functions for PDF splitting, Gemini extraction (structured output),
parsing, embedding, and Pinecone upsert.
"""

import hashlib
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF
from google import genai
from google.genai import types
from pydantic import BaseModel as PydanticBaseModel, Field
from pinecone import Pinecone

from app.core.categories import (
    CATEGORIES_PROMPT_LIST,
    GRANULAR_CATEGORIES,
    get_parent_category,
)
from promo_folders_pipelines.models import PromoItem
from promo_folders_pipelines.prompt_builder import build_system_prompt
from promo_folders_pipelines.stores import load_store_config

logger = logging.getLogger(__name__)

# Type alias — pipeline functions accept raw PDF bytes (downloaded from R2)
PdfData = bytes

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY", "")
PINECONE_INDEX_HOST = "promos-k16b2f4.svc.aped-4627-b74a.pinecone.io"

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
    original_description: str = Field(description="Full product text as printed in folder")
    normalized_name: str = Field(description="Lowercase product name WITHOUT brand, WITH variant/flavour")
    normalized_brand: Optional[str] = Field(default=None, description="Lowercase brand name")
    is_premium: bool = Field(description="true for national brands, false for house/store brands")
    packaging_type: Optional[str] = Field(default=None, description="Container: blik, fles, pet, zak, pot, doos, pak, brik, tube, spray, kuip, bakje, rol. null for loose")
    granular_category: str = Field(description="Category from provided list, or 'Other'")
    original_price: Optional[float] = Field(default=None, description="Regular price before promo")
    promo_price: Optional[float] = Field(default=None, description="Promotional price customer pays")
    promo_mechanism: Optional[str] = Field(default=None, description="Promo label as shown in folder")
    pack_size: Optional[int] = Field(default=None, description="Multi-pack count, 1 for singles")
    content_value: Optional[float] = Field(default=None, description="Size of ONE item: 6x33cl→33, 500g→500")
    content_unit: Optional[str] = Field(default=None, description="Unit lowercase: cl, ml, l, g, kg")
    unit_info: Optional[str] = Field(default=None, description="Raw unit string as printed: 6x33cl, 500g, 1L")
    page_number: Optional[int] = Field(default=None, description="Page within batch, 1-indexed")


class _PromoFolderSchema(PydanticBaseModel):
    validity_start: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    validity_end: Optional[str] = Field(default=None, description="YYYY-MM-DD")
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
                    temperature=1.0,
                    thinking_config=types.ThinkingConfig(thinking_level="high"),
                    response_mime_type="application/json",
                    response_schema=_PromoFolderSchema,
                    media_resolution=types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
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

    # Deduplicate by normalized_name (keep first occurrence)
    seen = set()
    deduped = []
    for item in all_items:
        name = (item.get("normalized_name") or "").lower().strip()
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
    """Parse Gemini structured output into validated PromoItem list."""
    validity_start = data.get("validity_start")
    validity_end = data.get("validity_end")
    if not validity_start or not validity_end:
        raise ValueError("Promo folder extraction is missing validity_start or validity_end")
    items = []

    for raw in data.get("items", []):
        granular = raw.get("granular_category", "Other")
        if granular not in GRANULAR_CATEGORIES:
            logger.warning(
                f"Unknown category '{granular}' for '{raw.get('original_description')}', defaulting to 'Other'"
            )
            granular = "Other"
        parent = get_parent_category(granular)

        normalized_name = (raw.get("normalized_name") or "").lower().strip()
        if not normalized_name:
            logger.warning(
                f"Skipping item with empty normalized_name: {raw.get('original_description')}"
            )
            continue

        normalized_brand = raw.get("normalized_brand")
        if normalized_brand:
            normalized_brand = normalized_brand.lower().strip()
            if not normalized_brand:
                normalized_brand = None

        # Safety net: strip brand from normalized_name if the LLM still included it
        if normalized_brand and normalized_name.startswith(normalized_brand):
            stripped = normalized_name[len(normalized_brand):].strip(" -")
            if stripped:
                logger.debug(
                    f"Stripped brand '{normalized_brand}' from normalized_name: "
                    f"'{normalized_name}' → '{stripped}'"
                )
                normalized_name = stripped

        packaging_type = raw.get("packaging_type")
        if packaging_type:
            packaging_type = packaging_type.lower().strip()
            if not packaging_type:
                packaging_type = None

        content_unit = raw.get("content_unit")
        if content_unit:
            content_unit = content_unit.lower().strip()
            if not content_unit:
                content_unit = None

        items.append(
            PromoItem(
                original_description=raw.get("original_description", ""),
                normalized_name=normalized_name,
                normalized_brand=normalized_brand,
                is_premium=bool(raw.get("is_premium", False)),
                packaging_type=packaging_type,
                granular_category=granular,
                parent_category=parent,
                original_price=_parse_price(raw.get("original_price")),
                promo_price=_parse_price(raw.get("promo_price")),
                promo_mechanism=(raw.get("promo_mechanism") or None),
                pack_size=_parse_int(raw.get("pack_size")),
                content_value=_parse_float(raw.get("content_value")),
                content_unit=content_unit,
                unit_info=raw.get("unit_info"),
                validity_start=validity_start,
                validity_end=validity_end,
                source_retailer=store_id,
                source_type="folder",
                page_number=raw.get("page_number"),
                promo_folder_url=promo_folder_url,
            )
        )

    logger.info(f"Parsed {len(items)} valid promo items")
    return items


def _parse_price(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Embedding & Pinecone
# ---------------------------------------------------------------------------
def build_embedding_text(item: PromoItem) -> str:
    """Build the text for Pinecone integrated embedding.

    Format: normalized_brand + normalized_name + [granular_category]
    Size, packaging, and quantity are excluded so that different pack
    formats of the same product produce identical embeddings.
    """
    parts = []
    if item.normalized_brand:
        parts.append(item.normalized_brand)
    parts.append(item.normalized_name)
    if item.granular_category and item.granular_category != "Other":
        parts.append(f"[{item.granular_category}]")
    return " ".join(parts)


def generate_record_id(item: PromoItem) -> str:
    """Generate a deterministic ID for a promo item."""
    key = (
        f"{item.source_retailer}:{item.original_description}:"
        f"{item.validity_start}:{item.validity_end}"
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _date_to_epoch(date_str: Optional[str]) -> int:
    """Convert YYYY-MM-DD to YYYYMMDD integer for Pinecone numeric filtering."""
    if not date_str:
        raise ValueError("Missing required validity date")
    try:
        return int(date_str.replace("-", ""))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid validity date: {date_str}") from exc


def delete_retailer_promos(index, retailer: str, validity_start: str, validity_end: str) -> int:
    """Delete existing promos for a retailer + validity period before re-ingesting."""
    logger.info(
        f"Cleaning up existing {retailer} promos "
        f"(validity {validity_start} to {validity_end})..."
    )

    ids_to_delete = []
    for id_batch in index.list(namespace="__default__"):
        if not id_batch:
            break
        fetched = index.fetch(ids=list(id_batch), namespace="__default__")
        for vec_id, vec in fetched.vectors.items():
            meta = vec.metadata or {}
            if (
                meta.get("source_retailer") == retailer
                and meta.get("validity_start") == validity_start
                and meta.get("validity_end") == validity_end
            ):
                ids_to_delete.append(vec_id)

    if ids_to_delete:
        for i in range(0, len(ids_to_delete), 100):
            batch = ids_to_delete[i : i + 100]
            index.delete(ids=batch, namespace="__default__")
        logger.info(f"Deleted {len(ids_to_delete)} existing records for {retailer} ({validity_start} to {validity_end})")
    else:
        logger.info(f"No existing records found for {retailer} ({validity_start} to {validity_end})")

    return len(ids_to_delete)


def clear_all_retailer_promos(retailer: str) -> int:
    """Delete ALL promos for a retailer regardless of validity period."""
    logger.info(f"Clearing ALL {retailer} promos from Pinecone index...")

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(host=PINECONE_INDEX_HOST)

    ids_to_delete = []
    for id_batch in index.list(namespace="__default__"):
        if not id_batch:
            break
        fetched = index.fetch(ids=list(id_batch), namespace="__default__")
        for vec_id, vec in fetched.vectors.items():
            meta = vec.metadata or {}
            if meta.get("source_retailer") == retailer:
                ids_to_delete.append(vec_id)

    if ids_to_delete:
        for i in range(0, len(ids_to_delete), 100):
            batch = ids_to_delete[i : i + 100]
            index.delete(ids=batch, namespace="__default__")
        logger.info(f"Deleted {len(ids_to_delete)} total records for {retailer}")
    else:
        logger.info(f"No existing records found for {retailer}")

    return len(ids_to_delete)


def nuke_entire_index() -> int:
    """Delete ALL records from the entire Pinecone promos index."""
    logger.info("Nuking ENTIRE Pinecone promos index...")

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(host=PINECONE_INDEX_HOST)

    ids_to_delete = []
    for id_batch in index.list(namespace="__default__"):
        if not id_batch:
            break
        ids_to_delete.extend(list(id_batch))

    if ids_to_delete:
        for i in range(0, len(ids_to_delete), 100):
            batch = ids_to_delete[i : i + 100]
            index.delete(ids=batch, namespace="__default__")
        logger.info(f"Deleted {len(ids_to_delete)} total records from index")
    else:
        logger.info("Index was already empty")

    return len(ids_to_delete)


def upsert_to_pinecone(items: list[PromoItem], batch_size: int = 50, auto_delete: bool = True) -> int:
    """Upsert promo items to Pinecone with integrated embedding.

    Args:
        auto_delete: If True, delete existing promos for same store+validity before upserting.
                     Set to False when ingesting multiple PDFs for the same store+validity
                     to avoid wiping items from previous PDFs.
    """
    if not items:
        logger.warning("No items to upsert")
        return 0

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(host=PINECONE_INDEX_HOST)

    # Delete existing records for this retailer + validity period
    if auto_delete:
        retailer = items[0].source_retailer
        validity_start = items[0].validity_start or ""
        validity_end = items[0].validity_end or ""
        if retailer and validity_start:
            delete_retailer_promos(index, retailer, validity_start, validity_end)

    records = []
    for item in items:
        if not item.validity_start or not item.validity_end:
            raise ValueError(
                f"Promo item '{item.normalized_name}' is missing validity window and cannot be indexed"
            )

        record = {
            "_id": generate_record_id(item),
            "text": build_embedding_text(item),
            "normalized_name": item.normalized_name,
            "is_premium": item.is_premium,
            "original_description": item.original_description,
            "granular_category": item.granular_category,
            "parent_category": item.parent_category,
            "validity_start": item.validity_start,
            "validity_end": item.validity_end,
            "validity_start_epoch": _date_to_epoch(item.validity_start),
            "validity_end_epoch": _date_to_epoch(item.validity_end),
            "source_retailer": item.source_retailer,
            "source_type": item.source_type,
        }
        if item.normalized_brand:
            record["normalized_brand"] = item.normalized_brand
        if item.packaging_type:
            record["packaging_type"] = item.packaging_type
        if item.original_price is not None:
            record["original_price"] = item.original_price
        if item.promo_price is not None:
            record["promo_price"] = item.promo_price
        if item.promo_mechanism:
            record["promo_mechanism"] = item.promo_mechanism
        if item.pack_size is not None:
            record["pack_size"] = item.pack_size
        if item.content_value is not None:
            record["content_value"] = item.content_value
        if item.content_unit:
            record["content_unit"] = item.content_unit
        if item.unit_info:
            record["unit_info"] = item.unit_info
        if item.page_number is not None:
            record["page_number"] = item.page_number
        if item.promo_folder_url:
            record["promo_folder_url"] = item.promo_folder_url
        records.append(record)

    total_upserted = 0
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        index.upsert_records(namespace="__default__", records=batch)
        total_upserted += len(batch)
        logger.info(
            f"Upserted batch {i // batch_size + 1}: {len(batch)} records "
            f"(total: {total_upserted})"
        )
        if i + batch_size < len(records):
            time.sleep(0.5)

    logger.info(f"Upsert complete: {total_upserted} records in Pinecone")
    return total_upserted


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------
def run_pipeline(
    store_id: str,
    pdf_data: bytes,
    promo_folder_url: Optional[str] = None,
    dry_run: bool = False,
    clear_index: bool = False,
    auto_delete: bool = True,
    pdf_label: str = "",
) -> list[PromoItem]:
    """Run the full ingestion pipeline for a store.

    Args:
        store_id: Canonical store name from stores.py (e.g. "colruyt")
        pdf_data: Raw PDF bytes (downloaded from R2)
        promo_folder_url: Optional URL of the promo folder source
        dry_run: If True, extract and parse only — no Pinecone upsert
        clear_index: If True, delete ALL existing promos for this store first
        auto_delete: If True, auto-delete existing promos for same store+validity
                     before upserting. Set to False for 2nd+ PDFs in multi-PDF ingestion.
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

    if not dry_run and not PINECONE_API_KEY:
        raise RuntimeError("PINECONE_API_KEY not set in environment")

    # Clear all retailer promos if requested
    if clear_index and not dry_run:
        clear_all_retailer_promos(canonical_store_id)

    # Step 1: Extract from PDF via Gemini
    raw_data = extract_promos_from_pdf(pdf_data, config)

    # Step 2: Parse and validate
    items = parse_promo_items(raw_data, canonical_store_id, promo_folder_url)

    if not items:
        logger.warning("No items extracted. Exiting.")
        return []

    # Step 3: Summary
    logger.info(f"\nExtracted {len(items)} promo items")
    if items[0].validity_start:
        logger.info(f"Validity: {items[0].validity_start} to {items[0].validity_end}")
    logger.info(f"Categories: {len(set(i.granular_category for i in items))} unique")
    logger.info(f"Brands: {len(set(i.normalized_brand for i in items if i.normalized_brand))} unique")

    for item in items[:5]:
        logger.info(
            f"  - {item.normalized_name} | {item.granular_category} | "
            f"promo: {item.promo_price} | {item.promo_mechanism or 'price reduction'}"
        )
    if len(items) > 5:
        logger.info(f"  ... and {len(items) - 5} more")

    # Step 4: Upsert or dry-run
    if dry_run:
        logger.info("DRY RUN — skipping Pinecone upsert")
    else:
        count = upsert_to_pinecone(items, auto_delete=auto_delete)
        logger.info(f"Done! {count} promo records in Pinecone 'promos' index.")

    return items

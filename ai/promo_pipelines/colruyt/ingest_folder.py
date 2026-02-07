#!/usr/bin/env python3
"""
Colruyt Promo Folder Ingestion Pipeline

Extracts promotional items from a Colruyt promo folder PDF using Gemini,
then upserts them into the Pinecone 'promos' index with integrated embedding.

Usage (from scandelicious-backend/):
    python ai/promo_pipelines/colruyt/ingest_folder.py promo_folder_colruyt.pdf
    python ai/promo_pipelines/colruyt/ingest_folder.py promo_folder_colruyt.pdf --dry-run
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF for PDF splitting

# Ensure backend root is on sys.path so we can import from app.*
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

from google import genai
from google.genai import types
from pinecone import Pinecone

from app.services.categories import CATEGORIES_PROMPT_LIST, GRANULAR_CATEGORIES, get_parent_category

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY", "")
PINECONE_INDEX_HOST = "promos-k16b2f4.svc.aped-4627-b74a.pinecone.io"

GEMINI_MODEL = "gemini-3-pro-preview"
MAX_OUTPUT_TOKENS = 16384
PAGES_PER_BATCH = 6
MAX_RETRIES = 4
RETRY_BASE_DELAY = 5  # seconds, doubles each retry
FOLDER_DIR = Path(__file__).resolve().parent / "folder"

RETAILER_NAME = "colruyt"
RETAILER_DISPLAY_NAME = "Colruyt"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class PromoItem:
    """A single promotional item extracted from the folder."""

    original_description: str
    normalized_name: str
    brand: Optional[str]
    granular_category: str
    parent_category: str
    original_price: Optional[float]
    promo_price: Optional[float]
    promo_mechanism: Optional[str]
    unit_info: Optional[str]
    validity_start: Optional[str]
    validity_end: Optional[str]
    source_retailer: str
    source_type: str
    page_number: Optional[int] = None
    promo_folder_url: Optional[str] = None


# ---------------------------------------------------------------------------
# Colruyt-specific Gemini prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = '''You are a specialist in extracting promotional offers from Colruyt supermarket folders (Belgium).
You have deep knowledge of Colruyt's folder layout, pricing labels, and promotional mechanics.

## COLRUYT FOLDER FORMAT
- Colruyt folders are typically bilingual: Dutch on one side, French on the other.
  Extract from EITHER language — do not duplicate items that appear in both languages.
- The validity period is printed on the cover page or footer: "Geldig van DD/MM tot DD/MM"
  or "Valable du DD/MM au DD/MM". Convert to YYYY-MM-DD (assume 2026 if year not shown).
- Apply the SAME validity dates to all items unless an item shows its own date range.
- If no dates are visible on these pages, use null.

## COLRUYT PROMO MECHANISMS
Colruyt uses specific promotional labels. Recognize and extract these correctly:
- **"Laagste Prijs"** / **"Prix le plus bas"**: Colruyt's core promise — these are regular promos, extract them normally
- **"1+1 gratis"** / **"1+1 gratuit"**: Buy one get one free. promo_price = price of the first item
- **"2e aan halve prijs"** / **"2ème à moitié prix"**: Second item at half price
- **"2+1 gratis"** / **"2+1 gratuit"**: Buy 2 get 1 free
- **"-30%"**, **"-25%"**, etc.: Percentage discount on the item
- **"€X.XX korting"**: Fixed euro discount
- **"X voor €Y"** / **"X pour €Y"**: Multi-buy deal (set promo_price to per-unit price)
- **"Mega Deal"**: A highlighted deal — extract as a normal promo with its mechanism
- Simple price reductions with no label: set promo_mechanism to null

## COLRUYT STORE BRANDS
Colruyt has three house brand tiers — always set brand to the house brand name:
- **Boni**: Standard store brand (mid-range quality)
- **Boni Selection**: Premium house brand
- **Everyday**: Budget/economy brand (cheapest tier)
- **CRU**: Premium delicatessen brand (high-end local/artisan products)

## EXTRACTION RULES

### For Each Promotional Item Extract:

1. **original_description**: Full product text as shown in the folder.
   Include brand, product name, variant, size/weight exactly as printed.
   Example: "Jupiler Pils Blikken 24x25cl"

2. **normalized_name**: Clean, generic, lowercase product name:
   - REMOVE the brand name (Jupiler, Boni, Everyday, Coca-Cola, Lay's, Danone, etc.)
   - REMOVE quantities (450ml, 1L, 500g, 6x33cl, 24x25cl, etc.)
   - REMOVE packaging (PET, Blik, Fles, Doos, Brik, etc.)
   - KEEP only what the product IS in its original language (Dutch or French)
   - Examples specific to Colruyt folders:
     - "Jupiler Pils Blikken 24x25cl" → "pils"
     - "Boni Volle Melk 1L" → "volle melk"
     - "Everyday Spaghetti 500g" → "spaghetti"
     - "CRU Ambachtelijk Brood" → "ambachtelijk brood"
     - "Coca-Cola Zero 1,5L PET" → "cola zero"
     - "Leffe Bruin Flessen 6x33cl" → "bruin bier"
     - "Lay's Chips Paprika 250g" → "chips paprika"
     - "Everyday Keukenrol 8st" → "keukenrol"
     - "Danone Activia Aardbei 4x125g" → "yoghurt aardbei"
     - "Dove Douchegel Original 250ml" → "douchegel"

3. **brand**: Brand/manufacturer in **lowercase**.
   - Store brands: "boni", "boni selection", "everyday", "cru"
   - Name brands: "jupiler", "coca-cola", "danone", "leffe", "lay's"
   - null for unbranded items (loose fruit, vegetables, bakery without brand)

4. **granular_category**: Assign ONE from this list:
{categories}

5. **original_price**: Regular price before promo (float, comma→dot). null if not shown.

6. **promo_price**: Promotional price the customer pays (float, comma→dot).
   - For "1+1 gratis": price of one item
   - For multi-buy "X voor €Y": per-unit price (€Y / X)
   - null if only a percentage/mechanism is shown

7. **promo_mechanism**: Promotional label as shown in the folder.
   - Examples: "1+1 gratis", "2e aan halve prijs", "-30%", "Mega Deal", "€1.00 korting"
   - null if it's just a simple price reduction with no label

8. **unit_info**: Package size/weight as shown.
   - Examples: "500g", "1L", "6x33cl", "per kg", "per stuk", "24x25cl"
   - null if not specified

9. **page_number**: The page number within the current batch where this item appears.
   - Pages are numbered starting from 1 within the batch provided
   - If an item spans multiple pages, use the first page where it appears

### IMPORTANT RULES
- Extract EVERY product, including small secondary items and non-food (household, personal care, pet)
- Each unique product appears ONCE — deduplicate across Dutch/French sides
- Colruyt "Laagste Prijs" items are standard promos — extract them
- Skip decorative elements, recipe suggestions, and store information

## OUTPUT FORMAT
Return ONLY valid JSON:
```json
{{
  "validity_start": "YYYY-MM-DD",
  "validity_end": "YYYY-MM-DD",
  "items": [
    {{
      "original_description": "Jupiler Pils Blikken 24x25cl",
      "normalized_name": "pils",
      "brand": "jupiler",
      "granular_category": "Beer Pils",
      "original_price": 12.99,
      "promo_price": 9.99,
      "promo_mechanism": null,
      "unit_info": "24x25cl",
      "page_number": 1
    }}
  ]
}}
```'''


# ---------------------------------------------------------------------------
# PDF splitting
# ---------------------------------------------------------------------------
def split_pdf_into_batches(pdf_path: Path, pages_per_batch: int) -> list[tuple[bytes, int]]:
    """Split a PDF into smaller PDFs of pages_per_batch pages each.

    Returns a list of (batch_bytes, start_page) tuples where start_page is 1-indexed.
    """
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    logger.info(f"PDF has {total_pages} pages, splitting into batches of {pages_per_batch}")

    batches = []
    for start in range(0, total_pages, pages_per_batch):
        end = min(start + pages_per_batch, total_pages)
        batch_doc = fitz.open()
        batch_doc.insert_pdf(doc, from_page=start, to_page=end - 1)
        # start_page is 1-indexed for user-friendly page numbers
        batches.append((batch_doc.tobytes(), start + 1))
        batch_doc.close()
        logger.info(f"  Batch {len(batches)}: pages {start + 1}-{end}")

    doc.close()
    return batches


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def _build_system_prompt() -> str:
    """Build the Gemini system prompt with injected categories."""
    return SYSTEM_PROMPT.format(categories=CATEGORIES_PROMPT_LIST)


def extract_batch(client: genai.Client, batch_pdf: bytes, batch_num: int, start_page: int, system_prompt: str) -> dict:
    """Extract promo items from a single PDF batch via Gemini with exponential backoff.

    Args:
        client: Gemini client
        batch_pdf: PDF bytes for this batch
        batch_num: Batch number (1-indexed)
        start_page: The 1-indexed page number in the original PDF where this batch starts
        system_prompt: The system prompt for Gemini
    """
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
                    f"Extract all promotional product offers from these {RETAILER_DISPLAY_NAME} promo folder pages. Return JSON only.",
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    temperature=0.1,
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

        json_str = _extract_json(response_text)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"{label} JSON parse error after {elapsed:.1f}s: {e}")
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Batch {batch_num} returned invalid JSON after {MAX_RETRIES} retries")
            continue

        # Adjust page numbers: Gemini returns 1-indexed page within batch,
        # we need to convert to actual PDF page number
        for item in data.get("items", []):
            batch_page = item.get("page_number")
            if batch_page is not None:
                # Convert batch-relative page (1-indexed) to actual PDF page
                item["page_number"] = start_page + batch_page - 1

        item_count = len(data.get("items", []))
        logger.info(f"{label} Done in {elapsed:.1f}s — {item_count} items extracted")
        return data

    return {"items": []}


def extract_promos_from_pdf(pdf_path: Path) -> dict:
    """Split PDF into batches and extract promo items sequentially with retries."""
    batches = split_pdf_into_batches(pdf_path, PAGES_PER_BATCH)
    system_prompt = _build_system_prompt()
    client = genai.Client(api_key=GEMINI_API_KEY)

    logger.info(f"Processing {len(batches)} batches sequentially...")
    start_time = time.time()

    all_items = []
    validity_start = None
    validity_end = None

    for i, (batch_pdf, start_page) in enumerate(batches):
        data = extract_batch(client, batch_pdf, i + 1, start_page, system_prompt)
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


def _extract_json(text: str) -> str:
    """Extract JSON from response, handling markdown code blocks."""
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    return text.strip()


# ---------------------------------------------------------------------------
# Parsing & validation
# ---------------------------------------------------------------------------
def load_metadata() -> dict:
    """Load metadata.json from the folder directory."""
    metadata_path = FOLDER_DIR / "metadata.json"
    if metadata_path.exists():
        with open(metadata_path) as f:
            return json.load(f)
    return {}


def parse_promo_items(data: dict) -> list[PromoItem]:
    """Parse Gemini response into validated PromoItem list."""
    validity_start = data.get("validity_start")
    validity_end = data.get("validity_end")
    items = []

    # Load promo_folder_url from metadata
    metadata = load_metadata()
    promo_folder_url = metadata.get("promo_folder_url")

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

        brand = raw.get("brand")
        if brand:
            brand = brand.lower().strip()

        # Safety net: strip brand from normalized_name if the LLM still included it
        if brand and normalized_name.startswith(brand):
            stripped = normalized_name[len(brand):].strip(" -")
            if stripped:
                logger.debug(
                    f"Stripped brand '{brand}' from normalized_name: "
                    f"'{normalized_name}' → '{stripped}'"
                )
                normalized_name = stripped

        items.append(
            PromoItem(
                original_description=raw.get("original_description", ""),
                normalized_name=normalized_name,
                brand=brand,
                granular_category=granular,
                parent_category=parent.value,
                original_price=_parse_price(raw.get("original_price")),
                promo_price=_parse_price(raw.get("promo_price")),
                promo_mechanism=raw.get("promo_mechanism"),
                unit_info=raw.get("unit_info"),
                validity_start=validity_start,
                validity_end=validity_end,
                source_retailer=RETAILER_NAME,
                source_type="folder",
                page_number=raw.get("page_number"),
                promo_folder_url=promo_folder_url,
            )
        )

    logger.info(f"Parsed {len(items)} valid promo items")
    return items


def _parse_price(val) -> Optional[float]:
    """Safely parse a price value to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Pinecone operations
# ---------------------------------------------------------------------------
def generate_record_id(item: PromoItem) -> str:
    """Generate a deterministic ID for a promo item."""
    key = (
        f"{item.source_retailer}:{item.original_description}:"
        f"{item.validity_start}:{item.validity_end}"
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def build_embedding_text(item: PromoItem) -> str:
    """Build the text for embedding: brand + normalized_name + unit_info + (granular_category)."""
    parts = []
    if item.brand:
        parts.append(item.brand)
    parts.append(item.normalized_name)
    if item.unit_info:
        parts.append(item.unit_info)
    if item.granular_category and item.granular_category != "Other":
        parts.append(f"({item.granular_category})")
    return " ".join(parts)


def delete_retailer_promos(index, retailer: str, validity_start: str, validity_end: str) -> int:
    """Delete all existing promos for a retailer + validity period before re-ingesting."""
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


def upsert_to_pinecone(items: list[PromoItem], batch_size: int = 50) -> int:
    """Upsert promo items to Pinecone with integrated embedding."""
    before = len(items)
    items = [i for i in items if i.promo_mechanism]
    if before > len(items):
        logger.info(f"Filtered out {before - len(items)} items with no promo_mechanism before upsert")

    if not items:
        logger.warning("No items with promo_mechanism to upsert")
        return 0

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(host=PINECONE_INDEX_HOST)

    # Delete existing records for this retailer + validity period to prevent duplicates
    retailer = items[0].source_retailer
    validity_start = items[0].validity_start or ""
    validity_end = items[0].validity_end or ""
    if retailer and validity_start:
        delete_retailer_promos(index, retailer, validity_start, validity_end)

    records = []
    for item in items:
        record = {
            "_id": generate_record_id(item),
            "text": build_embedding_text(item),
            "normalized_name": item.normalized_name,
            "original_description": item.original_description,
            "brand": item.brand or "",
            "granular_category": item.granular_category,
            "parent_category": item.parent_category,
            "original_price": item.original_price if item.original_price is not None else 0.0,
            "promo_price": item.promo_price if item.promo_price is not None else 0.0,
            "promo_mechanism": item.promo_mechanism or "",
            "unit_info": item.unit_info or "",
            "validity_start": item.validity_start or "",
            "validity_end": item.validity_end or "",
            "source_retailer": item.source_retailer,
            "source_type": item.source_type,
            "page_number": item.page_number if item.page_number is not None else 0,
            "promo_folder_url": item.promo_folder_url or "",
        }
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
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description=f"Ingest a {RETAILER_DISPLAY_NAME} promo folder PDF into the Pinecone promos index."
    )
    parser.add_argument(
        "pdf_filename",
        help=f"PDF filename in the folder/ directory (e.g., promo_folder_{RETAILER_NAME}.pdf)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract and parse only; do not upsert to Pinecone",
    )
    parser.add_argument(
        "--clear-index",
        action="store_true",
        help=f"Clear ALL existing {RETAILER_DISPLAY_NAME} promos from Pinecone before ingesting",
    )
    args = parser.parse_args()

    pdf_path = FOLDER_DIR / args.pdf_filename
    if not pdf_path.exists():
        logger.error(f"PDF not found: {pdf_path}")
        sys.exit(1)

    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY not set in environment")
        sys.exit(1)

    if not args.dry_run and not PINECONE_API_KEY:
        logger.error("PINECONE_API_KEY not set in environment")
        sys.exit(1)

    # Clear all retailer promos if requested
    if args.clear_index and not args.dry_run:
        if not PINECONE_API_KEY:
            logger.error("PINECONE_API_KEY not set in environment")
            sys.exit(1)
        clear_all_retailer_promos(RETAILER_NAME)

    # Step 1: Extract from PDF via Gemini
    logger.info("=" * 60)
    logger.info(f"{RETAILER_DISPLAY_NAME} Promo Folder Ingestion Pipeline")
    logger.info("=" * 60)
    logger.info(f"PDF: {pdf_path}")

    raw_data = extract_promos_from_pdf(pdf_path)

    # Step 2: Parse and validate
    items = parse_promo_items(raw_data)

    if not items:
        logger.warning("No items extracted. Exiting.")
        sys.exit(0)

    # Step 3: Summary
    logger.info("")
    logger.info(f"Extracted {len(items)} promo items")
    if items[0].validity_start:
        logger.info(f"Validity: {items[0].validity_start} to {items[0].validity_end}")
    logger.info(f"Categories: {len(set(i.granular_category for i in items))} unique")
    logger.info(f"Brands: {len(set(i.brand for i in items if i.brand))} unique")

    for item in items[:5]:
        logger.info(
            f"  - {item.normalized_name} | {item.granular_category} | "
            f"promo: {item.promo_price} | {item.promo_mechanism or 'price reduction'}"
        )
    if len(items) > 5:
        logger.info(f"  ... and {len(items) - 5} more")

    # Ensure results directory exists
    results_dir = FOLDER_DIR / "results"
    results_dir.mkdir(exist_ok=True)

    # Step 4: Upsert to Pinecone (or dry-run)
    if args.dry_run:
        logger.info("DRY RUN — skipping Pinecone upsert")
        output_path = results_dir / "extracted_promos.json"
        with open(output_path, "w") as f:
            json.dump(
                [
                    {
                        "normalized_name": i.normalized_name,
                        "original_description": i.original_description,
                        "brand": i.brand,
                        "granular_category": i.granular_category,
                        "parent_category": i.parent_category,
                        "original_price": i.original_price,
                        "promo_price": i.promo_price,
                        "promo_mechanism": i.promo_mechanism,
                        "unit_info": i.unit_info,
                        "validity_start": i.validity_start,
                        "validity_end": i.validity_end,
                        "page_number": i.page_number,
                        "promo_folder_url": i.promo_folder_url,
                    }
                    for i in items
                ],
                f,
                indent=2,
                ensure_ascii=False,
            )
        logger.info(f"Wrote {len(items)} items to {output_path}")
    else:
        count = upsert_to_pinecone(items)
        # Also save to results directory for reference
        output_path = results_dir / "extracted_promos.json"
        with open(output_path, "w") as f:
            json.dump(
                [
                    {
                        "normalized_name": i.normalized_name,
                        "original_description": i.original_description,
                        "brand": i.brand,
                        "granular_category": i.granular_category,
                        "parent_category": i.parent_category,
                        "original_price": i.original_price,
                        "promo_price": i.promo_price,
                        "promo_mechanism": i.promo_mechanism,
                        "unit_info": i.unit_info,
                        "validity_start": i.validity_start,
                        "validity_end": i.validity_end,
                        "page_number": i.page_number,
                        "promo_folder_url": i.promo_folder_url,
                    }
                    for i in items
                ],
                f,
                indent=2,
                ensure_ascii=False,
            )
        logger.info(f"Wrote {len(items)} items to {output_path}")
        logger.info(f"Done! {count} promo records in Pinecone 'promos' index.")


if __name__ == "__main__":
    main()

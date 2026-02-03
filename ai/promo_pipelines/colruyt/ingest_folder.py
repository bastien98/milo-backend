#!/usr/bin/env python3
"""
Colruyt Promo Folder Ingestion Pipeline

Extracts promotional items from a Colruyt promo folder PDF using Gemini,
then upserts them into the Pinecone 'promos' index with integrated embedding.

Splits the PDF into page batches and processes them in parallel for speed.

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

from app.services.categories import GRANULAR_CATEGORIES, get_parent_category

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


# ---------------------------------------------------------------------------
# Gemini prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a Belgian supermarket promotional folder analyzer specializing in Colruyt folders.
Extract ALL promotional product offers from the provided PDF folder pages.

## EXTRACTION RULES

### Validity Dates
- Look for the promo validity period, typically on the first/last page or page footers
- Format: "Geldig van DD/MM tot DD/MM" or "Valable du DD/MM au DD/MM"
- Convert to YYYY-MM-DD format (use 2026 as the year if only day/month shown)
- Apply the SAME validity dates to all items unless a specific item shows different dates
- If no validity dates are visible on these pages, use null

### For Each Promotional Item Extract:

1. **original_description**: The product description as shown in the folder
   - Include the full text: brand, product name, variant, size/weight
   - Example: "Jupiler Pils 24x25cl"

2. **normalized_name**: Clean semantic product name following these rules:
   - ALWAYS output in **lowercase**
   - REMOVE quantities (450ml, 1L, 500g, 10st, 6x33cl, 24x25cl, etc.)
   - REMOVE packaging types (PET, Blik, Fles, Doos, Brik, etc.)
   - REMOVE private label markers (Boni, 365, Everyday, Cara) when they don't define the product
   - KEEP brand names (Coca-Cola, Jupiler, Danone, Leffe, etc.)
   - Maintain original language (Dutch/French)
   - The goal: this name must match what appears on a Colruyt receipt after normalization
   - Examples:
     - "Jupiler Pils Blikken 24x25cl" → "jupiler"
     - "Boni Volle Melk 1L" → "volle melk"
     - "Coca-Cola Zero 1,5L PET" → "coca-cola zero"
     - "Leffe Bruin Flessen 6x33cl" → "leffe bruin"
     - "Boni Spaghetti 500g" → "spaghetti"
     - "Lay's Chips Paprika 250g" → "lay's chips paprika"
     - "Everyday Keukenrol 8st" → "keukenrol"

3. **brand**: The brand/manufacturer name in **lowercase**
   - For store brands: "boni", "everyday", "cru"
   - For name brands: "jupiler", "coca-cola", "danone"
   - null for unbranded generic items (loose fruit, vegetables)

4. **granular_category**: Assign ONE category from this list:
{categories}

5. **original_price**: The regular/original price before promotion (if shown), as a float
   - Convert comma decimals to dots: "2,99" → 2.99
   - null if not shown

6. **promo_price**: The promotional/discounted price, as a float
   - This is the price the customer actually pays during the promo
   - Convert comma decimals to dots
   - For "1+1 gratis" type promos, this is the price for the first item (you get the second free)
   - null if only a percentage/mechanism is shown without a concrete price

7. **promo_mechanism**: Description of the promotional mechanism
   - Examples: "1+1 gratis", "2e aan halve prijs", "-30%", "2+1 gratis", "€1.00 korting"
   - Use the text as shown in the folder
   - null if it is just a simple reduced price

8. **unit_info**: Package size or unit information
   - Examples: "500g", "1L", "6x33cl", "per kg", "per stuk", "24x25cl"
   - null if not specified

### IMPORTANT RULES
- Extract EVERY product shown in the folder, even if it appears small or secondary
- Do NOT skip non-food items (household, personal care, pet supplies, etc.)
- Each unique product should appear ONCE
- Colruyt "Laagste Prijs" (Lowest Price) items are regular promos — extract them normally
- For multi-buy promos (e.g., "2 voor €5"), set promo_price to the per-unit price (€2.50)
- Skip purely decorative elements, recipe suggestions, and store information

## OUTPUT FORMAT
Return ONLY valid JSON:
```json
{{
  "validity_start": "YYYY-MM-DD",
  "validity_end": "YYYY-MM-DD",
  "items": [
    {{
      "original_description": "Jupiler Pils Blikken 24x25cl",
      "normalized_name": "jupiler",
      "brand": "jupiler",
      "granular_category": "Beer (Pils)",
      "original_price": 12.99,
      "promo_price": 9.99,
      "promo_mechanism": null,
      "unit_info": "24x25cl"
    }}
  ]
}}
```"""


# ---------------------------------------------------------------------------
# PDF splitting
# ---------------------------------------------------------------------------
def split_pdf_into_batches(pdf_path: Path, pages_per_batch: int) -> list[bytes]:
    """Split a PDF into smaller PDFs of pages_per_batch pages each.

    Returns a list of PDF byte arrays, one per batch.
    """
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    logger.info(f"PDF has {total_pages} pages, splitting into batches of {pages_per_batch}")

    batches = []
    for start in range(0, total_pages, pages_per_batch):
        end = min(start + pages_per_batch, total_pages)
        batch_doc = fitz.open()  # new empty PDF
        batch_doc.insert_pdf(doc, from_page=start, to_page=end - 1)
        batches.append(batch_doc.tobytes())
        batch_doc.close()
        logger.info(f"  Batch {len(batches)}: pages {start + 1}-{end}")

    doc.close()
    return batches


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def _build_system_prompt() -> str:
    """Build the Gemini system prompt with injected categories."""
    categories_list = "\n".join(f"- {cat}" for cat in GRANULAR_CATEGORIES.keys())
    return SYSTEM_PROMPT.format(categories=categories_list)


def extract_batch(client: genai.Client, batch_pdf: bytes, batch_num: int, system_prompt: str) -> dict:
    """Extract promo items from a single PDF batch via Gemini with exponential backoff."""
    for attempt in range(1, MAX_RETRIES + 1):
        delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))  # 5s, 10s, 20s, 40s
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
                    "Extract all promotional product offers from these Colruyt promo folder pages. Return JSON only.",
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
        data = json.loads(json_str)
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

    for i, batch_pdf in enumerate(batches):
        data = extract_batch(client, batch_pdf, i + 1, system_prompt)
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
def parse_promo_items(data: dict) -> list[PromoItem]:
    """Parse Gemini response into validated PromoItem list."""
    validity_start = data.get("validity_start")
    validity_end = data.get("validity_end")
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

        brand = raw.get("brand")
        if brand:
            brand = brand.lower().strip()

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
                source_retailer="colruyt",
                source_type="folder",
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
# Pinecone upsert
# ---------------------------------------------------------------------------
def generate_record_id(item: PromoItem) -> str:
    """Generate a deterministic ID for a promo item.

    Uses a hash of retailer + original_description + validity period
    so re-running the same folder is idempotent.
    """
    key = (
        f"{item.source_retailer}:{item.original_description}:"
        f"{item.validity_start}:{item.validity_end}"
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def build_embedding_text(item: PromoItem) -> str:
    """Build a rich text for embedding that captures both the product and its category.

    Instead of embedding just "jupiler", we embed "jupiler - Beer (Pils)"
    so that semantically similar products (other beers) are close in vector space.
    This enables both exact matching AND finding alternatives.
    """
    parts = [item.normalized_name]
    if item.granular_category and item.granular_category != "Other":
        parts.append(item.granular_category)
    return " - ".join(parts)


def upsert_to_pinecone(items: list[PromoItem], batch_size: int = 50) -> int:
    """Upsert promo items to Pinecone with integrated embedding.

    The 'text' field is auto-embedded by Pinecone's integrated llama-text-embed-v2.
    It contains normalized_name + granular_category for richer semantic matching.
    All other fields are stored as metadata.
    """
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(host=PINECONE_INDEX_HOST)

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
        description="Ingest a Colruyt promo folder PDF into the Pinecone promos index."
    )
    parser.add_argument(
        "pdf_filename",
        help="PDF filename in the folder/ directory (e.g., promo_folder_colruyt.pdf)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract and parse only; do not upsert to Pinecone",
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

    # Step 1: Extract from PDF via Gemini (parallel batches)
    logger.info("=" * 60)
    logger.info("Colruyt Promo Folder Ingestion Pipeline")
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
    logger.info(
        f"Categories: {len(set(i.granular_category for i in items))} unique"
    )
    logger.info(
        f"Brands: {len(set(i.brand for i in items if i.brand))} unique"
    )

    for item in items[:5]:
        logger.info(
            f"  - {item.normalized_name} | {item.granular_category} | "
            f"promo: {item.promo_price} | {item.promo_mechanism or 'price reduction'}"
        )
    if len(items) > 5:
        logger.info(f"  ... and {len(items) - 5} more")

    # Step 4: Upsert to Pinecone
    if args.dry_run:
        logger.info("DRY RUN — skipping Pinecone upsert")
        output_path = FOLDER_DIR / "extracted_promos.json"
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
        logger.info(f"Done! {count} promo records in Pinecone 'promos' index.")


if __name__ == "__main__":
    main()

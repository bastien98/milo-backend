"""
Generic promo folder ingestion pipeline engine.

Shared functions for PDF splitting, Gemini extraction (structured output),
parsing, and PostgreSQL upsert.
"""

import base64
import hashlib
import io
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
import httpx
import replicate as replicate_lib
from PIL import Image
from pydantic import BaseModel as PydanticBaseModel, Field

from app.core.categories import (
    CATEGORIES_PROMPT_LIST,
    GRANULAR_CATEGORIES,
    get_parent_category,
)
from promo_folders_pipelines.models import PromoItem
from promo_folders_pipelines.promo_depth import compute_promo_depth
from promo_folders_pipelines.prompt_builder import build_system_prompt
from promo_folders_pipelines.r2_storage import R2PromoStorage
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
PAGES_PER_BATCH = 1  # Single page per Gemini call for maximum bbox accuracy
MAX_BATCH_BYTES = 1_500_000  # 1.5 MB — split oversized batches into single pages
MAX_RETRIES = 4
RETRY_BASE_DELAY = 5  # seconds, doubles each retry
REQUEST_TIMEOUT = 300  # 5 minutes per Gemini call


R2_PUBLIC_BASE_URL = os.environ.get("R2_PUBLIC_BASE_URL", "")

# Appended to the system prompt to instruct Gemini to return bounding boxes
_BBOX_PROMPT_SUFFIX = """

## BOUNDING BOX (PHYSICAL PRODUCT ONLY)
For EVERY item, populate the `bbox` field with a bounding box that safely and fully encompasses the **physical product itself** (e.g., the actual bottle, box, can, or crate).

CRITICAL RULES FOR BBOX:
1. CAPTURE THE WHOLE PRODUCT: Ensure the entire physical product is inside the box. Do NOT clip or shave off the edges, caps, or sides of the product. Leave a tiny visual margin (padding) around the physical item to ensure it is 100% intact.
2. EXCLUDE TEXT: DO NOT include the product name, price labels, volume information, or health warnings located below, above, or beside the product.
3. EXCLUDE PROMOS: DO NOT include promotional banners, ribbons, or discount badges unless they are physically printed onto the product packaging itself.
4. Coordinates are integers from 0 to 1000:
   x_min=0 → left edge, x_max=1000 → right edge
   y_min=0 → top edge,  y_max=1000 → bottom edge
5. Validation: x_min < x_max and y_min < y_max (set to null if uncertain).
6. One bbox per item, even if the product appears in multiple places on the page.

## TILE BOUNDING BOX (FULL PROMO TILE)
For EVERY item, ALSO populate the `tile_bbox` field with a bounding box that encompasses the **entire promo tile area** allocated to this product on the page — including the product image, price labels, brand text, promo badges, and background area.

CRITICAL RULES FOR TILE_BBOX:
1. CAPTURE EVERYTHING: Include the product image, price text, brand name, promo banner/ribbon, description, and any background color/shape that visually groups this item.
2. TIGHT FIT: The tile_bbox should tightly wrap the full visual area for this item. Do NOT include neighboring products' areas.
3. Coordinates are integers from 0 to 1000 (same system as bbox).
4. Validation: x_min < x_max and y_min < y_max (set to null if uncertain).
5. The tile_bbox will ALWAYS be equal to or larger than the bbox for the same item.
6. Ensure EVERY item has a tile_bbox. If you cannot determine exact boundaries, provide your best estimate rather than null.
7. MINIMIZE OVERLAPS: Tile bounding boxes should avoid overlapping where possible. For adjacent items in a grid, prefer tight boundaries that meet at the edge. Slight overlap is acceptable — never omit an item just because its tile_bbox would overlap a neighbor.
"""


# ---------------------------------------------------------------------------
# Pydantic schemas for Gemini structured output
# ---------------------------------------------------------------------------
class _BboxSchema(PydanticBaseModel):
    x_min: int = Field(ge=0, le=1000, description="Left edge, 0=left 1000=right")
    y_min: int = Field(ge=0, le=1000, description="Top edge, 0=top 1000=bottom")
    x_max: int = Field(ge=0, le=1000, description="Right edge, 0=left 1000=right")
    y_max: int = Field(ge=0, le=1000, description="Bottom edge, 0=top 1000=bottom")


class _PromoItemSchema(PydanticBaseModel):
    # --- Display fields (all required except display_unit_price) ---
    display_name: str = Field(description="Clean Title Case product label: product + variant + size. Omit brand when product is identifiable without it (e.g., 'Chips Explosions Salt & Pepper 150 g' not 'Croky Chips...'). Keep brand when it IS the product identity (e.g., 'Coca-Cola Zero 1,5 L' — 'Zero 1,5 L' alone is meaningless). ALWAYS include size/quantity when visible. For drinks, volume is CRITICAL (e.g., '33 cl', '6 x 25 cl', '1,5 L'). No promo text or pricing.")
    display_mechanism: str = Field(description="Standardized promo label. Title case, consistent formatting. For conditional percentage discounts, ALWAYS include the condition (e.g., '-25% Vanaf 2 Verpakkingen', NOT just '-25%'). Only use bare '-25%' if the discount applies to a single item with no minimum purchase. Examples: '1+1 Gratis', '-25%', '-25% Vanaf 2 Verpakkingen', '-20% Vanaf 3 Flessen', '-30% Vanaf 12 Blikken', '2e aan Halve Prijs', '2+1 Gratis', 'Prijsverlaging'.")
    display_description: Optional[str] = Field(default=None, description="Plain-language Dutch explanation of the deal (~80 chars max). Explain what the shopper needs to DO and what they GET. Examples: 'Koop 2 en krijg de 3e gratis', 'Nu €0.80 goedkoper per stuk'. null if unclear.")
    display_savings_label: Optional[str] = Field(default=None, description="Human-friendly savings text. Examples: '1 Gratis Item', 'Bespaar €3.00', 'Tot -25% Korting', '2e aan Halve Prijs'. null if unclear.")
    display_unit_price: Optional[str] = Field(default=None, description="Price per standard unit computed from promo_price and size info visible on the page. Use Belgian units: €/L for drinks, €/kg for food, €/stuk for countable items, €/rol for paper products, €/stuk for tea bags/tabs/doekjes. For wine assume 75 cl, for beer blik assume 33 cl. Format: '€X.XX/unit'. null ONLY if no size info whatsoever.")

    # --- Brand identification ---
    normalized_brand: Optional[str] = Field(default=None, description="Lowercase brand/manufacturer name only. Use the EXACT same format as receipt brand extraction: 'jupiler', 'coca-cola', 'boni', 'boni selection', 'milbona', 'lay\\'s', 'delhaize', '365'. For store/house brands use their actual name (e.g., 'boni', '365', 'everyday', 'milbona', 'pikok'), NEVER 'in-house'. null only for truly unbranded generic assortment promos (very rare in promo folders).")
    display_brand: Optional[str] = Field(default=None, description="Brand name in clean Title Case for UI display: 'Jupiler', 'Coca-Cola', 'Boni Selection', 'Lay\\'s', '365'. null when normalized_brand is null.")

    # --- Price reasoning (scratchpad — generated before prices to improve accuracy) ---
    price_reasoning: str = Field(description="Show your work: what is the promo mechanism, what prices are visible on the page, and how you calculated promo_price and savings_amount step by step. This field is not displayed to users.")

    # --- Pricing (all required, non-negative) ---
    original_price: Optional[float] = Field(default=0.0, ge=0, description="Regular price before promo, rounded to 2 decimal places. If not visible, set equal to promo_price.")
    promo_price: float = Field(ge=0, description="Price of ONE item/pack as shown on shelf. For ANY X+Y gratis deal (1+1, 2+1, 3+3, 4+1, 12+6, etc.): ALWAYS same as original_price. For -25%: original_price × 0.75. For X voor €Y: €Y ÷ X. Rounded to 2 decimal places.")
    savings_amount: Optional[float] = Field(default=0.0, ge=0, description="Total euro savings when completing the deal. 0.0 if unknown.")

    # --- Purchase quantity (for promo depth calculation) ---
    min_purchase_qty: int = Field(ge=1, description="Minimum number of items/packs a shopper must buy to complete the deal. For 1+1 Gratis: 2. For 2+1 Gratis: 3. For 12+6 Gratis: 18. For 2e aan Halve Prijs: 2. For 2e aan -70%: 2. For -25%: 1. For -25% Vanaf 2 Verpakkingen: 2. For -30% Vanaf 12 Blikken: 12. For Prijsverlaging: 1. For 3 voor €5: 3.")

    # --- Category ---
    granular_category: str = Field(description="Category from the provided list, or 'Other' if nothing fits.")

    # --- Page reference ---
    page_number: int = Field(ge=1, description="Page number within the current PDF batch, 1-indexed.")

    # --- Bounding box (for image cropping) ---
    bbox: Optional[_BboxSchema] = Field(
        default=None,
        description=(
            "Bounding box around the physical product only (bottle, box, package, can). "
            "Exclude text, price labels, and promo badges. Leave a small margin around "
            "the product. Integer coords 0-1000 (0=left/top, 1000=right/bottom). "
            "x_min < x_max, y_min < y_max. null if the product cannot be clearly located."
        ),
    )

    # --- Tile bounding box (for tap hotspots in app) ---
    tile_bbox: _BboxSchema = Field(
        description=(
            "REQUIRED bounding box around the ENTIRE promo tile area for this item — including "
            "the product image, price label, brand text, promo badge, and background. "
            "This is always equal to or larger than bbox. Integer coords 0-1000. "
            "x_min < x_max, y_min < y_max. Always provide your best estimate."
        ),
    )


class _PromoFolderSchema(PydanticBaseModel):
    validity_start: Optional[date] = Field(default=None, description="Folder validity start date")
    validity_end: Optional[date] = Field(default=None, description="Folder validity end date")
    items: list[_PromoItemSchema] = Field(description="All promotional items extracted")


# ---------------------------------------------------------------------------
# Bbox validation schemas (second-pass verification)
# ---------------------------------------------------------------------------

class _BboxValidationItem(PydanticBaseModel):
    item_index: int = Field(description="0-based index of the item in the input list")
    tile_bbox: _BboxSchema = Field(description="Corrected or confirmed tile bounding box (0-1000 coords)")
    bbox: Optional[_BboxSchema] = Field(default=None, description="Corrected or confirmed product-only bbox (0-1000 coords)")
    status: str = Field(description="'confirmed' if bbox was already correct, 'corrected' if adjusted, 'added' if was previously missing")


class _BboxValidationResult(PydanticBaseModel):
    items: list[_BboxValidationItem] = Field(description="Validated bounding boxes for each input item")


_BBOX_VALIDATION_PROMPT = """You are verifying bounding box accuracy for promo items on a supermarket folder page.

For EACH item listed below, verify that its tile_bbox correctly encompasses the ENTIRE promo tile area
(product image + price label + brand text + promo badge + background). Also verify the bbox (product-only).

Rules:
- If the bbox is correct, return it unchanged with status "confirmed"
- If the bbox is wrong (too small, shifted, covers wrong area), correct it with status "corrected"
- If the bbox is null/missing, locate the item on the page and provide one with status "added"
- Coordinates are integers 0-1000 (0=left/top, 1000=right/bottom)
- tile_bbox must encompass the full promo tile; bbox must tightly wrap the physical product only
- Return ALL items, even if confirmed unchanged

Items to verify:
"""


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
    full_system_prompt = system_prompt + _BBOX_PROMPT_SUFFIX
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
                    f"Extract all promotional product offers from this {display_name} promo folder page.",
                ],
                config=types.GenerateContentConfig(
                    system_instruction=full_system_prompt,
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


def extract_batch_images(
    client: genai.Client,
    images: list[tuple[int, bytes]],
    batch_num: int,
    system_prompt: str,
    display_name: str,
) -> dict:
    """Extract promo items from a batch of page images via Gemini structured output.

    Args:
        images: List of (page_number, webp_bytes) tuples (1-indexed page numbers)
        batch_num: Batch sequence number for logging
    """
    full_system_prompt = system_prompt + _BBOX_PROMPT_SUFFIX
    for attempt in range(1, MAX_RETRIES + 1):
        delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
        label = f"[Batch {batch_num}]"
        total_bytes = sum(len(b) for _, b in images)
        page_nums = [p for p, _ in images]

        if attempt == 1:
            logger.info(f"{label} Sending pages {page_nums} to Gemini ({total_bytes:,} bytes)...")
        else:
            logger.info(f"{label} Retry {attempt}/{MAX_RETRIES} after {delay}s backoff...")
            time.sleep(delay)

        start_time = time.time()

        # Build content parts: one image per page + text instruction
        parts = []
        for _, img_bytes in images:
            parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/webp"))
        parts.append(
            types.Part.from_text(
                text=f"Extract all promotional product offers from this {display_name} promo folder page."
            )
        )

        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=parts,
                config=types.GenerateContentConfig(
                    system_instruction=full_system_prompt,
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

        cleaned = re.sub(r',\s*([}\]])', r'\1', response_text)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning(f"{label} JSON parse error: {e}")
            if attempt == MAX_RETRIES:
                raise
            continue

        # Adjust page numbers: batch-relative → absolute page number
        first_page = page_nums[0]
        for item in data.get("items", []):
            batch_page = item.get("page_number")
            if batch_page is not None:
                item["page_number"] = first_page + batch_page - 1

        item_count = len(data.get("items", []))
        logger.info(f"{label} Done in {elapsed:.1f}s — {item_count} items extracted")
        return data

    return {"items": []}


def validate_page_bboxes(
    client: genai.Client,
    page_image: bytes,
    page_number: int,
    items_on_page: list[dict],
    display_name: str,
) -> list[dict]:
    """Second-pass bbox validation: verify and correct bboxes for items on a single page.

    Sends the page image + list of items with their current bboxes to Gemini,
    asking it to verify/correct each bbox and fill in missing ones.

    Args:
        client: Gemini API client
        page_image: WebP bytes of the page image
        page_number: 1-indexed page number
        items_on_page: List of raw item dicts from the extraction pass
        display_name: Store display name for logging

    Returns:
        Updated list of item dicts with corrected bbox/tile_bbox values
    """
    if not items_on_page:
        return items_on_page

    label = f"[{display_name} p{page_number} validate]"

    # Build the item list for the validation prompt
    item_descriptions = []
    for i, item in enumerate(items_on_page):
        name = item.get("display_name", "Unknown")
        tile_bbox = item.get("tile_bbox")
        bbox = item.get("bbox")

        tile_str = f"[{tile_bbox['x_min']}, {tile_bbox['y_min']}, {tile_bbox['x_max']}, {tile_bbox['y_max']}]" if tile_bbox else "null (LOCATE THIS ITEM)"
        bbox_str = f"[{bbox['x_min']}, {bbox['y_min']}, {bbox['x_max']}, {bbox['y_max']}]" if bbox else "null"

        item_descriptions.append(f"{i}. \"{name}\" — tile_bbox: {tile_str}, bbox: {bbox_str}")

    items_text = "\n".join(item_descriptions)
    full_prompt = _BBOX_VALIDATION_PROMPT + items_text

    for attempt in range(1, MAX_RETRIES + 1):
        delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
        if attempt > 1:
            logger.info(f"{label} Retry {attempt}/{MAX_RETRIES} after {delay}s backoff...")
            time.sleep(delay)

        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=page_image, mime_type="image/webp"),
                    types.Part.from_text(text="Verify and correct the bounding boxes for the items listed in the system prompt."),
                ],
                config=types.GenerateContentConfig(
                    system_instruction=full_prompt,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    temperature=0.0,
                    thinking_config=types.ThinkingConfig(thinking_level="medium"),
                    response_mime_type="application/json",
                    response_schema=_BboxValidationResult,
                    media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
                ),
            )
        except Exception as e:
            logger.warning(f"{label} API error: {e}")
            if attempt == MAX_RETRIES:
                logger.error(f"{label} Validation failed after {MAX_RETRIES} retries, returning original items")
                return items_on_page
            continue

        response_text = ""
        if response.candidates:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    response_text += part.text

        if not response_text:
            if attempt == MAX_RETRIES:
                logger.warning(f"{label} Empty validation response, returning original items")
                return items_on_page
            continue

        try:
            cleaned = re.sub(r',\s*([}\]])', r'\1', response_text)
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning(f"{label} JSON parse error: {e}")
            if attempt == MAX_RETRIES:
                return items_on_page
            continue

        # Apply validated bboxes back to items
        validated_items = data.get("items", [])
        confirmed = corrected = added = 0

        for vi in validated_items:
            idx = vi.get("item_index")
            if idx is None or idx < 0 or idx >= len(items_on_page):
                continue

            status = vi.get("status", "confirmed")
            if status == "confirmed":
                confirmed += 1
            elif status == "corrected":
                corrected += 1
            elif status == "added":
                added += 1

            # Update tile_bbox (convert back to the raw format Gemini returns)
            new_tile = vi.get("tile_bbox")
            if new_tile and isinstance(new_tile, dict):
                items_on_page[idx]["tile_bbox"] = new_tile

            # Update bbox
            new_bbox = vi.get("bbox")
            if new_bbox and isinstance(new_bbox, dict):
                items_on_page[idx]["bbox"] = new_bbox

        logger.info(f"{label} Validation: {confirmed} confirmed, {corrected} corrected, {added} added")
        return items_on_page

    return items_on_page


def extract_promos_from_images(
    page_images: list[tuple[int, bytes]],
    config: Dict[str, Any],
) -> dict:
    """Extract promo items from page images via Gemini (batched, 2 pages per call).

    Args:
        page_images: List of (page_number, webp_bytes) tuples, 1-indexed
        config: Store YAML config dict

    Returns:
        Dict with keys: validity_start, validity_end, items
    """
    system_prompt = build_system_prompt(config, CATEGORIES_PROMPT_LIST)
    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options={"timeout": REQUEST_TIMEOUT * 1000},
    )
    display_name = config["display_name"]

    # Batch images in pairs (2 per call)
    batches = []
    for i in range(0, len(page_images), PAGES_PER_BATCH):
        batches.append(page_images[i : i + PAGES_PER_BATCH])

    logger.info(f"Processing {len(batches)} image batches ({len(page_images)} pages) sequentially...")
    start_time = time.time()

    all_items = []
    validity_start = None
    validity_end = None

    for i, batch in enumerate(batches):
        data = extract_batch_images(client, batch, i + 1, system_prompt, display_name)
        if data.get("validity_start") and not validity_start:
            validity_start = data["validity_start"]
            validity_end = data.get("validity_end")
        all_items.extend(data.get("items", []))

    elapsed = time.time() - start_time
    logger.info(f"All batches complete in {elapsed:.1f}s — {len(all_items)} total items")

    # Validation pass: verify and correct bboxes per page
    validate = config.get("validate_bboxes", True)
    if validate and all_items:
        logger.info("Starting bbox validation pass...")
        validation_start = time.time()

        # Build a lookup of page_number → image bytes
        image_lookup = {num: img for num, img in page_images}

        # Group items by page_number
        from collections import defaultdict
        items_by_page: dict[int, list[tuple[int, dict]]] = defaultdict(list)
        for idx, item in enumerate(all_items):
            pn = item.get("page_number")
            if pn is not None:
                items_by_page[pn].append((idx, item))

        for pn, indexed_items in sorted(items_by_page.items()):
            page_img = image_lookup.get(pn)
            if not page_img:
                continue

            page_items = [item for _, item in indexed_items]
            validated = validate_page_bboxes(client, page_img, pn, page_items, display_name)

            # Write validated items back to all_items
            for (orig_idx, _), new_item in zip(indexed_items, validated):
                all_items[orig_idx] = new_item

        validation_elapsed = time.time() - validation_start
        logger.info(f"Bbox validation complete in {validation_elapsed:.1f}s")

    # Deduplicate: only remove cross-page duplicates (bilingual NL/FR).
    # Same name on the SAME page = different products (e.g., different beer brands).
    seen_names: dict[str, int] = {}  # name → first page seen
    deduped = []
    for item in all_items:
        name = (item.get("display_name") or "").lower().strip()
        page = item.get("page_number")
        if name and name in seen_names and seen_names[name] != page:
            logger.debug(f"Dedup: skipping cross-page duplicate '{name}' (first on p{seen_names[name]}, dup on p{page})")
            continue
        if name and name not in seen_names:
            seen_names[name] = page
        deduped.append(item)

    if len(deduped) < len(all_items):
        logger.info(f"Deduplicated: {len(all_items)} → {len(deduped)} items")

    return {
        "validity_start": validity_start,
        "validity_end": validity_end,
        "items": deduped,
    }


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

    # Deduplicate: only remove cross-page duplicates (bilingual NL/FR).
    # Same name on the SAME page = different products (e.g., different beer brands).
    seen_names: dict[str, int] = {}  # name → first page seen
    deduped = []
    for item in all_items:
        name = (item.get("display_name") or "").lower().strip()
        page = item.get("page_number")
        if name and name in seen_names and seen_names[name] != page:
            logger.debug(f"Dedup: skipping cross-page duplicate '{name}' (first on p{seen_names[name]}, dup on p{page})")
            continue
        if name and name not in seen_names:
            seen_names[name] = page
        deduped.append(item)

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

        # Extract fields with sensible defaults (coverage over quality)
        original_price = _parse_price(raw.get("original_price")) or 0.0
        promo_price = _parse_price(raw.get("promo_price")) or 0.0
        savings_amount = _parse_price(raw.get("savings_amount")) or 0.0
        display_mechanism = (raw.get("display_mechanism") or "").strip() or "Promo"
        display_description = (raw.get("display_description") or "").strip() or display_mechanism
        display_savings_label = (raw.get("display_savings_label") or "").strip() or "Promo"

        # Round prices to 2 decimal places
        original_price = round(original_price, 2)
        promo_price = round(promo_price, 2)
        savings_amount = round(savings_amount, 2)

        # Purchase quantity & promo depth
        min_purchase_qty = max(1, int(raw.get("min_purchase_qty", 1)))
        promo_depth = compute_promo_depth(savings_amount, original_price, min_purchase_qty) if original_price > 0 else 0

        # Brand extraction (default to "unknown" if missing)
        normalized_brand = (raw.get("normalized_brand") or "").strip().lower() or "unknown"
        display_brand = (raw.get("display_brand") or "").strip() or None

        # Category validation
        granular = raw.get("granular_category", "Other")
        if granular not in GRANULAR_CATEGORIES:
            logger.warning(f"Unknown category '{granular}' for '{display_name}', defaulting to 'Other'")
            granular = "Other"
        parent = get_parent_category(granular)

        # Extract bbox (product-only, used for image cropping + persisted)
        # Gemini returns 0-1000 integers; convert to 0-1 floats for storage
        raw_bbox = raw.get("bbox")
        bbox_dict = None
        if raw_bbox and isinstance(raw_bbox, dict):
            x_min = raw_bbox.get("x_min")
            y_min = raw_bbox.get("y_min")
            x_max = raw_bbox.get("x_max")
            y_max = raw_bbox.get("y_max")
            if (
                x_min is not None and y_min is not None
                and x_max is not None and y_max is not None
                and x_min < x_max and y_min < y_max
            ):
                bbox_dict = {
                    "x_min": x_min / 1000.0,
                    "y_min": y_min / 1000.0,
                    "x_max": x_max / 1000.0,
                    "y_max": y_max / 1000.0,
                }

        # Extract tile_bbox (full promo tile area, used for tap hotspots)
        raw_tile_bbox = raw.get("tile_bbox")
        tile_bbox_dict = None
        if raw_tile_bbox and isinstance(raw_tile_bbox, dict):
            tx_min = raw_tile_bbox.get("x_min")
            ty_min = raw_tile_bbox.get("y_min")
            tx_max = raw_tile_bbox.get("x_max")
            ty_max = raw_tile_bbox.get("y_max")
            if (
                tx_min is not None and ty_min is not None
                and tx_max is not None and ty_max is not None
                and tx_min < tx_max and ty_min < ty_max
            ):
                tile_bbox_dict = {
                    "x_min": tx_min / 1000.0,
                    "y_min": ty_min / 1000.0,
                    "x_max": tx_max / 1000.0,
                    "y_max": ty_max / 1000.0,
                }

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
                normalized_brand=normalized_brand,
                display_brand=display_brand,
                granular_category=granular,
                parent_category=parent,
                validity_start=validity_start,
                validity_end=validity_end,
                source_retailer=store_id,
                source_type="folder",
                page_number=raw.get("page_number"),
                promo_folder_url=promo_folder_url,
                bbox=bbox_dict,
                tile_bbox=tile_bbox_dict,
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
# Image enhancement via Recraft (upscale)
# ---------------------------------------------------------------------------
REPLICATE_API_TOKEN = os.environ.get("REPLICATE_API_TOKEN", "")
def _upscale_image(crop: Image.Image, item_label: str = "") -> Image.Image:
    """Upscale a cropped product image 4x using Recraft Crisp Upscale on Replicate.

    Returns an RGB image at 4x the input resolution.
    """
    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    buf.seek(0)
    image_data_uri = "data:image/png;base64," + base64.b64encode(buf.read()).decode()

    for attempt in range(1, MAX_RETRIES + 1):
        delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
        label = f"[Upscale {item_label}]" if item_label else "[Upscale]"

        if attempt > 1:
            logger.info(f"{label} Retry {attempt}/{MAX_RETRIES} after {delay}s backoff...")
            time.sleep(delay)

        try:
            output = replicate_lib.run(
                "recraft-ai/recraft-crisp-upscale",
                input={"image": image_data_uri},
            )

            image_url = output[0] if isinstance(output, list) else output
            resp = httpx.get(str(image_url), timeout=120)
            resp.raise_for_status()
            result = Image.open(io.BytesIO(resp.content)).convert("RGB")
            logger.info(f"{label} Upscaled {crop.size[0]}x{crop.size[1]} → {result.size[0]}x{result.size[1]}")
            return result

        except Exception as e:
            logger.warning(f"{label} Attempt {attempt} failed: {e}")
            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"Upscale failed after {MAX_RETRIES} retries for: {item_label}"
                ) from e

    raise RuntimeError(f"Upscale failed after {MAX_RETRIES} retries for: {item_label}")


def enhance_item_image(
    crop: Image.Image,
    item_label: str = "",
) -> Image.Image:
    """Enhance a cropped product image by upscaling 4x via Recraft Crisp Upscale on Replicate.

    Raises on failure after retries.
    """
    w, h = crop.size
    if w < 64 or h < 64:
        raise RuntimeError(
            f"Crop too small ({w}x{h}) for enhancement: {item_label}"
        )

    label = f"[Enhance {item_label}]" if item_label else "[Enhance]"

    upscaled = _upscale_image(crop, item_label)
    logger.info(f"{label} Enhanced successfully ({upscaled.size[0]}x{upscaled.size[1]})")
    return upscaled


# ---------------------------------------------------------------------------
# Page image rendering + item image cropping
# ---------------------------------------------------------------------------
def _render_pdf_pages(pdf_data: bytes, dpi: int = 150) -> dict[int, bytes]:
    """Render each PDF page to a WebP image at the given DPI.

    Returns {page_number: webp_bytes} (1-indexed).
    150 DPI on A4 ≈ 1240×1754px — sufficient for 800px crops.
    """
    doc = fitz.open(stream=pdf_data, filetype="pdf")
    pages = {}
    for i in range(len(doc)):
        pixmap = doc[i].get_pixmap(dpi=dpi)
        pages[i + 1] = pixmap.tobytes("webp")
    doc.close()
    return pages


def _pad_to_square(img: Image.Image, bg_color=(255, 255, 255)) -> Image.Image:
    """Pad image to a square canvas with the given background color."""
    w, h = img.size
    if w == h:
        return img
    size = max(w, h)
    square = Image.new("RGB", (size, size), bg_color)
    square.paste(img, ((size - w) // 2, (size - h) // 2))
    return square


def _resize_to_max(img: Image.Image, max_dim: int) -> Image.Image:
    """Resize image so its largest dimension equals max_dim, preserving aspect ratio."""
    w, h = img.size
    if max(w, h) <= max_dim:
        return img.copy()
    scale = max_dim / max(w, h)
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


def crop_and_upload_item_images(
    items: list[PromoItem],
    page_images: dict[int, bytes],
    r2: R2PromoStorage,
    store_id: str,
    enhance: bool = True,
) -> None:
    """Crop each item's product tile from upscaled pages and upload 3 sizes to R2.

    When enhance=True, upscales each *page* once via Replicate, then crops all
    items from the high-res page. This is far more cost-efficient than upscaling
    each individual crop (1 Replicate call per page instead of per item).

    Sets thumbnail_url, image_url, hero_url on each item that has a valid bbox.
    Items without a bbox are skipped gracefully.
    """
    if not R2_PUBLIC_BASE_URL:
        logger.warning("R2_PUBLIC_BASE_URL not set — skipping image upload")
        return

    # Pre-upscale pages that have items with bboxes (1 Replicate call per page)
    upscaled_pages: dict[int, Image.Image] = {}
    if enhance and REPLICATE_API_TOKEN:
        pages_needed = {
            item.page_number
            for item in items
            if item.bbox and item.page_number and item.page_number in page_images
        }
        logger.info(f"Upscaling {len(pages_needed)} pages via Replicate (1 call per page)...")
        for page_num in sorted(pages_needed):
            try:
                page_img = Image.open(io.BytesIO(page_images[page_num])).convert("RGB")
                upscaled = _upscale_image(page_img, item_label=f"page {page_num}")
                upscaled_pages[page_num] = upscaled
            except Exception as e:
                logger.warning(f"Page {page_num} upscale failed: {e} — will use original resolution")

    uploaded = 0
    skipped_no_bbox = 0
    skipped_invalid = 0

    for item in items:
        if not item.bbox:
            skipped_no_bbox += 1
            continue

        page_num = item.page_number
        if not page_num or page_num not in page_images:
            skipped_invalid += 1
            continue

        bbox = item.bbox
        x_min = bbox.get("x_min", 0)
        y_min = bbox.get("y_min", 0)
        x_max = bbox.get("x_max", 0)
        y_max = bbox.get("y_max", 0)

        # Validate bbox geometry and minimum area
        if x_min >= x_max or y_min >= y_max:
            skipped_invalid += 1
            continue
        area = (x_max - x_min) * (y_max - y_min)
        if area < 0.0025:  # 0.25% of page area — allow smaller items
            skipped_invalid += 1
            continue

        # Use upscaled page if available, otherwise fall back to original
        if page_num in upscaled_pages:
            page_img = upscaled_pages[page_num]
        else:
            try:
                page_img = Image.open(io.BytesIO(page_images[page_num])).convert("RGB")
            except Exception as e:
                logger.warning(f"Could not open page {page_num} image: {e}")
                skipped_invalid += 1
                continue

        pw, ph = page_img.size

        # Add 2% padding around bbox to avoid clipping product edges
        pad_x = int(0.02 * pw)
        pad_y = int(0.02 * ph)
        x1 = max(0, int(x_min * pw) - pad_x)
        y1 = max(0, int(y_min * ph) - pad_y)
        x2 = min(pw, int(x_max * pw) + pad_x)
        y2 = min(ph, int(y_max * ph) + pad_y)

        if (x2 - x1) < 64 or (y2 - y1) < 64:
            skipped_invalid += 1
            continue

        crop = page_img.crop((x1, y1, x2, y2))

        # Pad to square for uniform display in iOS grid
        crop = _pad_to_square(crop)

        record_id = generate_record_id(item)
        base_key = f"promo_item_images/{store_id}/{record_id}"

        try:
            for size, suffix in ((200, "thumb"), (400, "medium"), (800, "hero")):
                resized = _resize_to_max(crop, size)
                buf = io.BytesIO()
                resized.save(buf, format="WEBP", quality=85)
                r2.upload_image(f"{base_key}/{suffix}.webp", buf.getvalue())

            item.thumbnail_url = f"{R2_PUBLIC_BASE_URL}/{base_key}/thumb.webp"
            item.image_url = f"{R2_PUBLIC_BASE_URL}/{base_key}/medium.webp"
            item.hero_url = f"{R2_PUBLIC_BASE_URL}/{base_key}/hero.webp"
            uploaded += 1
        except Exception as e:
            logger.warning(f"Image upload failed for '{item.display_name}': {e}")

    logger.info(
        f"Item images: {uploaded} uploaded, "
        f"{skipped_no_bbox} skipped (no bbox), "
        f"{skipped_invalid} skipped (invalid bbox/page)"
    )


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
            # Extract bbox coordinates (None if bbox is missing)
            bbox = item.bbox or {}
            tile = item.tile_bbox or {}

            cur.execute(
                """
                INSERT INTO promo_items (
                    id, display_name, display_name_lower, display_mechanism,
                    display_description, display_savings_label, display_unit_price,
                    normalized_brand, display_brand,
                    original_price, promo_price, savings_amount, min_purchase_qty, promo_depth,
                    granular_category, source_retailer, source_type,
                    page_number, promo_folder_url, validity_start, validity_end,
                    thumbnail_url, image_url, hero_url,
                    bbox_x_min, bbox_y_min, bbox_x_max, bbox_y_max,
                    tile_bbox_x_min, tile_bbox_y_min, tile_bbox_x_max, tile_bbox_y_max
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    display_name_lower = EXCLUDED.display_name_lower,
                    display_mechanism = EXCLUDED.display_mechanism,
                    display_description = EXCLUDED.display_description,
                    display_savings_label = EXCLUDED.display_savings_label,
                    display_unit_price = EXCLUDED.display_unit_price,
                    normalized_brand = EXCLUDED.normalized_brand,
                    display_brand = EXCLUDED.display_brand,
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
                    validity_end = EXCLUDED.validity_end,
                    thumbnail_url = EXCLUDED.thumbnail_url,
                    image_url = EXCLUDED.image_url,
                    hero_url = EXCLUDED.hero_url,
                    bbox_x_min = EXCLUDED.bbox_x_min,
                    bbox_y_min = EXCLUDED.bbox_y_min,
                    bbox_x_max = EXCLUDED.bbox_x_max,
                    bbox_y_max = EXCLUDED.bbox_y_max,
                    tile_bbox_x_min = EXCLUDED.tile_bbox_x_min,
                    tile_bbox_y_min = EXCLUDED.tile_bbox_y_min,
                    tile_bbox_x_max = EXCLUDED.tile_bbox_x_max,
                    tile_bbox_y_max = EXCLUDED.tile_bbox_y_max
                """,
                (
                    record_id,
                    item.display_name,
                    item.display_name.lower(),
                    item.display_mechanism,
                    item.display_description,
                    item.display_savings_label,
                    item.display_unit_price,
                    item.normalized_brand,
                    item.display_brand,
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
                    item.thumbnail_url,
                    item.image_url,
                    item.hero_url,
                    bbox.get("x_min"),
                    bbox.get("y_min"),
                    bbox.get("x_max"),
                    bbox.get("y_max"),
                    tile.get("x_min"),
                    tile.get("y_min"),
                    tile.get("x_max"),
                    tile.get("y_max"),
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

    # Step 2.5: Crop item images, enhance via Replicate FLUX, and upload to R2
    page_images = _render_pdf_pages(pdf_data)
    r2 = R2PromoStorage()
    crop_and_upload_item_images(items, page_images, r2, canonical_store_id)

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

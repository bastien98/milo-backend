"""
Generic promo folder ingestion pipeline engine.

Shared functions for PDF splitting, Gemini extraction (structured output),
parsing, and PostgreSQL upsert.
"""

import hashlib
import io
import json
import logging
import os
import re
import time
from datetime import date
from typing import Any, Dict, List, Literal, Optional

import fitz  # PyMuPDF
from google import genai
from google.genai import types
import httpx
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
from promo_folders_pipelines.unit_pricing import compute_unit_price, validate_pack_size

logger = logging.getLogger(__name__)

# Type alias — pipeline functions accept raw PDF bytes (downloaded from R2)
PdfData = bytes

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

GEMINI_MODEL = "gemini-3-pro-preview"
MAX_OUTPUT_TOKENS = 65536
PAGES_PER_BATCH = 1  # Single page per Gemini call for maximum bbox accuracy
MAX_BATCH_BYTES = 1_500_000  # 1.5 MB — split oversized batches into single pages
MAX_RETRIES = 4
RETRY_BASE_DELAY = 5  # seconds, doubles each retry
REQUEST_TIMEOUT = 300  # 5 minutes per Gemini call


R2_PUBLIC_BASE_URL = os.environ.get("R2_PUBLIC_BASE_URL", "")

# Appended to the system prompt to instruct Gemini to return bounding boxes
_BBOX_PROMPT_SUFFIX = """

## BOUNDING BOX (PHYSICAL PRODUCT ONLY)
For EVERY item, populate the `bbox` field with a bounding box around the **physical product itself** (e.g., the actual bottle, box, can, or crate).

CRITICAL RULES FOR BBOX:
1. CAPTURE THE WHOLE PRODUCT: The entire physical product must be inside the box. Do NOT clip caps, lids, or edges.
2. FIXED MARGIN: Leave exactly 2-3% of the tile's shortest side as margin around the physical product — no more, no less. The crop must look consistent across products: neither tight-cropped nor surrounded by whitespace.
3. EXCLUDE TEXT: Do NOT include product names, price labels, volume information, or health warnings that sit outside the packaging.
4. EXCLUDE PROMOS: Do NOT include promotional banners, ribbons, or discount badges unless they are physically printed onto the product packaging itself.
5. Coordinates are integers from 0 to 1000:
   x_min=0 → left edge, x_max=1000 → right edge
   y_min=0 → top edge,  y_max=1000 → bottom edge
6. Validation: x_min < x_max and y_min < y_max (set to null only if the product cannot be located at all).
7. One bbox per item, even if the product appears in multiple places on the page.

## TILE BOUNDING BOX (FULL PROMO TILE)
For EVERY item, populate the `tile_bbox` field with a bounding box around the **entire promo tile** — product image, price labels, brand text, promo badges/ribbons, and the background shape or color block that visually groups this item.

CRITICAL RULES FOR TILE_BBOX:
1. CAPTURE EVERYTHING: Include the product image AND every price/brand/promo element that visually belongs to this item. Missing a price label or promo badge is a failure.
2. NEIGHBOR OVERLAP IS OK: In dense grids, tile_bboxes MAY touch or slightly overlap their neighbors at the shared edge. Do not shrink a tile_bbox inward just to avoid an overlap — that cuts off price labels. Each item's price label and badges must always be inside its own tile_bbox.
3. Coordinates are integers 0-1000 (same system as bbox).
4. Validation: x_min < x_max and y_min < y_max. tile_bbox must always fully contain bbox.
5. Always provide a tile_bbox for every item. Use your best estimate rather than null.

## WORKED EXAMPLE
For a 1L milk carton whose packaging spans coords [110, 210, 250, 400] and has a price label below at y=420-500 and a "-25%" badge in the top-right corner of its tile:
  bbox       = [106, 206, 254, 404]   (product with ~2-3% margin, excludes price label and badge)
  tile_bbox  = [80,  190, 290, 520]   (includes badge, product, price label, and background)

NEGATIVE EXAMPLE — DO NOT DO THIS:
  bbox       = [80,  190, 290, 520]   (wrong — that's the tile, not just the product)
  tile_bbox  = [110, 210, 250, 400]   (wrong — cuts off the price label and badge)

## CONFIDENCE
For EVERY item, populate `bbox_confidence` with your confidence that BOTH bbox and tile_bbox are correct:
  1.0 = product edges are crisp, tile boundaries are unambiguous.
  0.7-0.9 = standard case with minor ambiguity.
  0.4-0.6 = product is stylized, partially occluded, or the tile layout is unclear.
  0.0-0.3 = you are guessing the location.
Be honest — low confidence is more useful than optimistic guesses.
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
    # --- Display fields ---
    display_name: str = Field(description="Clean Title Case product label: product + variant + size. Omit brand when product is identifiable without it (e.g., 'Chips Explosions Salt & Pepper 150 g' not 'Croky Chips...'). Keep brand when it IS the product identity (e.g., 'Coca-Cola Zero 1,5 L' — 'Zero 1,5 L' alone is meaningless). ALWAYS include size/quantity when visible. For drinks, volume is CRITICAL (e.g., '33 cl', '6 x 25 cl', '1,5 L'). No promo text or pricing.")
    display_mechanism: str = Field(description="Standardized promo label. Title case, consistent formatting. For conditional percentage discounts, ALWAYS include the condition (e.g., '-25% Vanaf 2 Verpakkingen', NOT just '-25%'). Only use bare '-25%' if the discount applies to a single item with no minimum purchase. Examples: '1+1 Gratis', '-25%', '-25% Vanaf 2 Verpakkingen', '-20% Vanaf 3 Flessen', '-30% Vanaf 12 Blikken', '2e aan Halve Prijs', '2+1 Gratis', 'Prijsverlaging'.")
    display_description: Optional[str] = Field(default=None, description="Plain-language Dutch explanation of the deal (~80 chars max). Explain what the shopper needs to DO and what they GET. Examples: 'Koop 2 en krijg de 3e gratis', 'Nu €0.80 goedkoper per stuk'. null if unclear.")
    display_savings_label: Optional[str] = Field(default=None, description="Human-friendly savings text. Examples: '1 Gratis Item', 'Bespaar €3.00', 'Tot -25% Korting', '2e aan Halve Prijs'. null if unclear.")

    # --- Pack size (observable tokens; Python computes unit price from these) ---
    pack_size_value: Optional[float] = Field(default=None, ge=0, description="Numeric size of ONE unit in the pack as printed on the page. '500 g'→500, '1,5 L'→1.5, '6 x 25 cl'→25, 'Box 12 capsules'→12, '4-pack toiletpapier 6 rollen'→6. Comma→dot. null if no size visible.")
    pack_size_unit: Optional[Literal['g','kg','ml','cl','l','stuk','rol','doekje','capsule','tab','zakje']] = Field(default=None, description="Unit of pack_size_value EXACTLY as implied on the page, lowercased. Do NOT convert (cl stays cl, g stays g). Countables→'stuk'. Toilet/kitchen paper→'rol'. Tea bags→'zakje'. Dishwasher/washing tabs→'tab'. Coffee/Nespresso→'capsule'. Wipes→'doekje'.")
    pack_count: int = Field(default=1, ge=1, description="Number of individual units in the pack. '6 x 25 cl'→6, '24 blikjes 33 cl'→24, '4-pack toiletpapier 6 rollen'→4, '1,5 L'→1, '500 g'→1, '3-pack'→3. Default 1 for single items.")
    pack_size_reasoning: Optional[str] = Field(default=None, description="Brief scratchpad: which tokens on the page led to pack_size_value/unit/count. Not displayed to users.")

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
    page_number: int = Field(ge=1, description="Position of the item's page within THIS batch (1-indexed). For a single-page batch, ALWAYS return 1. For multi-page batches: 1 for first page, 2 for second, etc. Do NOT return the absolute page number from the full document.")

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

    # --- Bbox confidence (routing signal, not persisted) ---
    bbox_confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description=(
            "Your confidence that both bbox and tile_bbox are correct, 0.0-1.0. "
            "Lower it when the product is stylized, occluded, or the tile layout is ambiguous."
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
(product image + price label + brand text + promo badge + background). Also verify the bbox (product-only
with a 2-3% margin around the physical product).

Rules:
- Items tagged [CONFIRM ONLY — do not modify] are already validated by a high-confidence extraction. Return them unchanged with status "confirmed". Do NOT relocate, shrink, or expand them.
- Items tagged [REVIEW — check and correct if wrong] may have errors. Correct only if you are sure the current bbox is wrong.
- If the bbox is correct, return it unchanged with status "confirmed"
- If the bbox is wrong (too small, shifted, covers wrong area), correct it with status "corrected"
- If the bbox is null/missing, locate the item on the page and provide one with status "added"
- Coordinates are integers 0-1000 (0=left/top, 1000=right/bottom)
- tile_bbox must encompass the full promo tile; bbox must tightly wrap the physical product only with a small margin
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

        # Bump temperature on retries to avoid deterministic truncation
        temp = 0.0 if attempt == 1 else 0.2

        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=parts,
                config=types.GenerateContentConfig(
                    system_instruction=full_system_prompt,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    temperature=temp,
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
        last_page = page_nums[-1]
        for item in data.get("items", []):
            batch_page = item.get("page_number")
            if batch_page is not None:
                adjusted = first_page + batch_page - 1
                # Clamp to valid range (Gemini sometimes returns absolute page numbers)
                if adjusted < first_page or adjusted > last_page:
                    logger.warning(f"{label} Item '{item.get('display_name', '?')}' had page_number={batch_page}, clamping to batch range")
                    adjusted = max(first_page, min(adjusted, last_page))
                item["page_number"] = adjusted

        item_count = len(data.get("items", []))
        logger.info(f"{label} Done in {elapsed:.1f}s — {item_count} items extracted")
        return data

    return {"items": []}


def _iou(a: dict | None, b: dict | None) -> float:
    """Intersection-over-union for two bbox dicts in the 0-1000 coord system."""
    if not a or not b:
        return 0.0
    ix1 = max(a["x_min"], b["x_min"])
    iy1 = max(a["y_min"], b["y_min"])
    ix2 = min(a["x_max"], b["x_max"])
    iy2 = min(a["y_max"], b["y_max"])
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0, a["x_max"] - a["x_min"]) * max(0, a["y_max"] - a["y_min"])
    area_b = max(0, b["x_max"] - b["x_min"]) * max(0, b["y_max"] - b["y_min"])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _contains(outer: dict | None, inner: dict | None) -> bool:
    if not outer or not inner:
        return False
    return (
        inner["x_min"] >= outer["x_min"]
        and inner["y_min"] >= outer["y_min"]
        and inner["x_max"] <= outer["x_max"]
        and inner["y_max"] <= outer["y_max"]
    )


def _expand_to_contain(outer: dict, inner: dict, buffer: int = 10) -> dict:
    """Return a copy of outer expanded so it fully contains inner, plus a small buffer.

    Coords are in the 0-1000 system. `buffer` is absolute (10 ≈ 1% of page edge).
    """
    return {
        "x_min": max(0, min(outer["x_min"], inner["x_min"] - buffer)),
        "y_min": max(0, min(outer["y_min"], inner["y_min"] - buffer)),
        "x_max": min(1000, max(outer["x_max"], inner["x_max"] + buffer)),
        "y_max": min(1000, max(outer["y_max"], inner["y_max"] + buffer)),
    }


def _clip_to(inner: dict, outer: dict) -> dict:
    """Return a copy of inner clipped to stay within outer."""
    return {
        "x_min": max(inner["x_min"], outer["x_min"]),
        "y_min": max(inner["y_min"], outer["y_min"]),
        "x_max": min(inner["x_max"], outer["x_max"]),
        "y_max": min(inner["y_max"], outer["y_max"]),
    }


def _max_iou_with_others(candidate: dict, others: list[dict | None]) -> float:
    """Highest IoU between `candidate` and any non-null bbox in `others`."""
    best = 0.0
    for other in others:
        if not other:
            continue
        val = _iou(candidate, other)
        if val > best:
            best = val
    return best


def _is_suspect_original(bbox: dict | None, confidence: float | None) -> bool:
    """True when the original bbox looks geometrically suspect and deserves a looser IoU gate.

    Cases: low area (<1% of page), touches a page edge, or model reports low confidence.
    """
    if not bbox:
        return True
    if confidence is not None and confidence < 0.5:
        return True
    width = bbox["x_max"] - bbox["x_min"]
    height = bbox["y_max"] - bbox["y_min"]
    if width <= 0 or height <= 0:
        return True
    if (width * height) < 10_000:  # <1% of 1000×1000 page
        return True
    if bbox["x_min"] <= 2 or bbox["y_min"] <= 2 or bbox["x_max"] >= 998 or bbox["y_max"] >= 998:
        return True
    return False


IOU_REJECT_THRESHOLD = 0.3
IOU_REJECT_THRESHOLD_SUSPECT = 0.15
NEIGHBOR_OVERLAP_IOU_LIMIT = 0.2  # tile_bbox expansion is blocked if it overlaps neighbors more than this
CONFIDENCE_SKIP_VALIDATION = 0.9  # items above this are not modified by the validation pass


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

    # Flag high-confidence items so the validator (and our post-processing) leave them alone.
    skip_modification = [
        float(item.get("bbox_confidence") or 0.0) >= CONFIDENCE_SKIP_VALIDATION
        for item in items_on_page
    ]
    skip_count = sum(skip_modification)

    # Build the item list for the validation prompt
    item_descriptions = []
    for i, item in enumerate(items_on_page):
        name = item.get("display_name", "Unknown")
        tile_bbox = item.get("tile_bbox")
        bbox = item.get("bbox")
        confidence = item.get("bbox_confidence")

        tile_str = f"[{tile_bbox['x_min']}, {tile_bbox['y_min']}, {tile_bbox['x_max']}, {tile_bbox['y_max']}]" if tile_bbox else "null (LOCATE THIS ITEM)"
        bbox_str = f"[{bbox['x_min']}, {bbox['y_min']}, {bbox['x_max']}, {bbox['y_max']}]" if bbox else "null"
        flag = "[CONFIRM ONLY — do not modify]" if skip_modification[i] else "[REVIEW — check and correct if wrong]"
        conf_str = f" conf={confidence:.2f}" if isinstance(confidence, (int, float)) else ""

        item_descriptions.append(f"{i}. {flag} \"{name}\"{conf_str} — tile_bbox: {tile_str}, bbox: {bbox_str}")

    items_text = "\n".join(item_descriptions)
    full_prompt = _BBOX_VALIDATION_PROMPT + items_text
    if skip_count:
        logger.info(f"{label} {skip_count}/{len(items_on_page)} items marked high-confidence and exempt from modification")

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
                    thinking_config=types.ThinkingConfig(thinking_level="high"),
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
        confirmed = corrected = added = skipped_high_conf = 0

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

            orig_tile = items_on_page[idx].get("tile_bbox")
            orig_bbox = items_on_page[idx].get("bbox")
            confidence = items_on_page[idx].get("bbox_confidence")

            # High-confidence items are exempt from modification; only missing bboxes can be filled.
            if skip_modification[idx]:
                skipped_high_conf += 1
                if not orig_tile and vi.get("tile_bbox"):
                    items_on_page[idx]["tile_bbox"] = vi["tile_bbox"]
                if not orig_bbox and vi.get("bbox"):
                    items_on_page[idx]["bbox"] = vi["bbox"]
            else:
                # Asymmetric IoU threshold: looser bar when the original bbox looks geometrically suspect.
                tile_threshold = (
                    IOU_REJECT_THRESHOLD_SUSPECT
                    if _is_suspect_original(orig_tile, confidence)
                    else IOU_REJECT_THRESHOLD
                )
                bbox_threshold = (
                    IOU_REJECT_THRESHOLD_SUSPECT
                    if _is_suspect_original(orig_bbox, confidence)
                    else IOU_REJECT_THRESHOLD
                )

                # tile_bbox: reject drastic corrections, keep original on null regression
                new_tile = vi.get("tile_bbox")
                if new_tile and isinstance(new_tile, dict):
                    if orig_tile:
                        iou = _iou(orig_tile, new_tile)
                        if iou < tile_threshold:
                            logger.warning(
                                f"{label} Rejecting tile_bbox correction for item {idx} "
                                f"('{items_on_page[idx].get('display_name', '?')}'): IoU={iou:.2f} "
                                f"below threshold {tile_threshold}"
                            )
                        else:
                            items_on_page[idx]["tile_bbox"] = new_tile
                    else:
                        items_on_page[idx]["tile_bbox"] = new_tile
                # else: validator returned null — keep original (null-regression guard)

                # bbox: same guards
                new_bbox = vi.get("bbox")
                if new_bbox and isinstance(new_bbox, dict):
                    if orig_bbox:
                        iou = _iou(orig_bbox, new_bbox)
                        if iou < bbox_threshold:
                            logger.warning(
                                f"{label} Rejecting bbox correction for item {idx} "
                                f"('{items_on_page[idx].get('display_name', '?')}'): IoU={iou:.2f} "
                                f"below threshold {bbox_threshold}"
                            )
                        else:
                            items_on_page[idx]["bbox"] = new_bbox
                    else:
                        items_on_page[idx]["bbox"] = new_bbox

            # Containment: bbox must sit inside tile_bbox. Try non-destructive recovery.
            final_tile = items_on_page[idx].get("tile_bbox")
            final_bbox = items_on_page[idx].get("bbox")
            if final_bbox and final_tile and not _contains(final_tile, final_bbox):
                # Step 1: attempt to expand tile_bbox to contain bbox + small buffer.
                expanded_tile = _expand_to_contain(final_tile, final_bbox, buffer=10)
                # Only accept the expansion if it doesn't chew into a neighbor's tile.
                other_tiles = [
                    items_on_page[j].get("tile_bbox")
                    for j in range(len(items_on_page))
                    if j != idx
                ]
                neighbor_overlap = _max_iou_with_others(expanded_tile, other_tiles)
                if neighbor_overlap <= NEIGHBOR_OVERLAP_IOU_LIMIT:
                    logger.info(
                        f"{label} bbox escaped tile for item {idx} — "
                        f"expanding tile_bbox (neighbor IoU={neighbor_overlap:.2f})"
                    )
                    items_on_page[idx]["tile_bbox"] = expanded_tile
                else:
                    # Step 2: clip bbox to tile_bbox so the product-only intent is preserved.
                    clipped = _clip_to(final_bbox, final_tile)
                    # Guard against degenerate clip (zero/negative area).
                    if clipped["x_max"] > clipped["x_min"] and clipped["y_max"] > clipped["y_min"]:
                        logger.warning(
                            f"{label} bbox escaped tile for item {idx} and expansion would "
                            f"overlap neighbor (IoU={neighbor_overlap:.2f}) — "
                            f"clipping bbox to tile_bbox instead"
                        )
                        items_on_page[idx]["bbox"] = clipped
                    else:
                        # Step 3: last resort — fall back to tile_bbox and flag for review.
                        logger.warning(
                            f"{label} bbox escaped tile for item {idx} "
                            f"('{items_on_page[idx].get('display_name', '?')}') and neither "
                            f"expand nor clip is viable — falling back bbox := tile_bbox (REVIEW)"
                        )
                        items_on_page[idx]["bbox"] = dict(final_tile)

        logger.info(
            f"{label} Validation: {confirmed} confirmed, {corrected} corrected, "
            f"{added} added, {skipped_high_conf} high-confidence exempt"
        )
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
                logger.warning(f"No image found for page {pn} — skipping bbox validation for {len(indexed_items)} item(s)")
                continue

            page_items = [item for _, item in indexed_items]
            validated = validate_page_bboxes(client, page_img, pn, page_items, display_name)

            # Write validated items back to all_items
            for (orig_idx, _), new_item in zip(indexed_items, validated):
                all_items[orig_idx] = new_item

        validation_elapsed = time.time() - validation_start
        logger.info(f"Bbox validation complete in {validation_elapsed:.1f}s")

    return {
        "validity_start": validity_start,
        "validity_end": validity_end,
        "items": all_items,
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

    return {
        "validity_start": validity_start,
        "validity_end": validity_end,
        "items": all_items,
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
    raw_items = data.get("items", [])
    logger.info(f"Parsing {len(raw_items)} raw items from Gemini output")

    for raw in raw_items:
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

        if original_price == 0.0 and promo_price == 0.0:
            logger.warning(f"Item '{display_name}' (p{raw.get('page_number')}): both prices are 0.0")

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
            else:
                logger.warning(f"Item '{display_name}' (p{raw.get('page_number')}): invalid tile_bbox coords")
        else:
            logger.warning(f"Item '{display_name}' (p{raw.get('page_number')}): missing tile_bbox")

        if not bbox_dict:
            logger.debug(f"Item '{display_name}' (p{raw.get('page_number')}): no product bbox")

        # Pack size tokens (Gemini-extracted); Python computes the unit price from these.
        pack_size_value = _parse_price(raw.get("pack_size_value"))
        pack_size_unit = (raw.get("pack_size_unit") or "").strip().lower() or None
        pack_count = max(1, int(raw.get("pack_count") or 1))

        unit_price = compute_unit_price(
            promo_price=promo_price,
            original_price=original_price,
            min_purchase_qty=min_purchase_qty,
            savings_amount=savings_amount,
            pack_size_value=pack_size_value,
            pack_size_unit=pack_size_unit,
            pack_count=pack_count,
            display_name=display_name,
            granular_category=granular,
        )

        # Validation — flag gross pack-size mismatches but don't drop the row.
        mismatch = validate_pack_size(display_name, pack_size_value, pack_size_unit)
        if mismatch:
            logger.warning(f"Item '{display_name}' (p{raw.get('page_number')}): {mismatch}")
        for warn in unit_price.warnings:
            logger.info(f"Item '{display_name}' (p{raw.get('page_number')}): unit-price {warn}")

        items.append(
            PromoItem(
                display_name=display_name,
                display_mechanism=display_mechanism,
                display_description=display_description,
                display_savings_label=display_savings_label,
                display_unit_price=unit_price.display_unit_price,
                original_price=original_price,
                promo_price=promo_price,
                savings_amount=savings_amount,
                unit_price_value=unit_price.unit_price_value,
                unit_price_unit=unit_price.unit_price_unit,
                unit_price_quality=unit_price.quality,
                pack_size_value=pack_size_value,
                pack_size_unit=pack_size_unit,
                pack_count=pack_count,
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
        logger.info(f"Skipped {skipped} items with empty display_name")

    # Per-page summary
    page_counts: dict[int, dict] = {}
    for item in items:
        pn = item.page_number or 0
        if pn not in page_counts:
            page_counts[pn] = {"total": 0, "with_tile_bbox": 0, "with_bbox": 0}
        page_counts[pn]["total"] += 1
        if item.tile_bbox:
            page_counts[pn]["with_tile_bbox"] += 1
        if item.bbox:
            page_counts[pn]["with_bbox"] += 1

    for pn in sorted(page_counts):
        c = page_counts[pn]
        logger.info(f"  Page {pn}: {c['total']} items, {c['with_tile_bbox']} with tile_bbox, {c['with_bbox']} with bbox")

    logger.info(f"Parsed {len(items)} promo items from {len(page_counts)} pages")
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
# Page image rendering + item image cropping
# ---------------------------------------------------------------------------
def _render_pdf_pages(pdf_data: bytes, dpi: int = 200) -> dict[int, bytes]:
    """Render each PDF page to a WebP image at the given DPI.

    Returns {page_number: webp_bytes} (1-indexed).
    200 DPI on A4 ≈ 1653×2338px — preserves small-product edges for Gemini bbox extraction.
    Uses Pillow with quality=95, method=6 so WebP encoding is pinned instead of relying
    on PyMuPDF's default (which has varied across versions and produced lossy page images).
    """
    doc = fitz.open(stream=pdf_data, filetype="pdf")
    pages = {}
    for i in range(len(doc)):
        pixmap = doc[i].get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=95, method=6)
        pages[i + 1] = buf.getvalue()
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
    folder_index: int = 1,
) -> None:
    """Crop each item's product tile from pages and upload 3 sizes to R2.

    Sets thumbnail_url, image_url, hero_url on each item that has a valid bbox.
    Items without a bbox are skipped gracefully.
    """
    if not R2_PUBLIC_BASE_URL:
        logger.warning("R2_PUBLIC_BASE_URL not set — skipping image upload")
        return

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

        try:
            page_img = Image.open(io.BytesIO(page_images[page_num])).convert("RGB")
        except Exception as e:
            logger.warning(f"Could not open page {page_num} image: {e}")
            skipped_invalid += 1
            continue

        pw, ph = page_img.size

        # No post-crop padding — the extraction prompt already instructs Gemini to leave
        # a 2-3% margin around the physical product. Adding more here double-pads the crop
        # and produces inconsistent whitespace across products.
        x1 = max(0, int(x_min * pw))
        y1 = max(0, int(y_min * ph))
        x2 = min(pw, int(x_max * pw))
        y2 = min(ph, int(y_max * ph))

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
                    unit_price_value, unit_price_unit, unit_price_quality,
                    pack_size_value, pack_size_unit, pack_count,
                    normalized_brand, display_brand,
                    original_price, promo_price, savings_amount, min_purchase_qty, promo_depth,
                    granular_category, source_retailer, source_type,
                    page_number, promo_folder_url, validity_start, validity_end,
                    thumbnail_url, image_url, hero_url,
                    bbox_x_min, bbox_y_min, bbox_x_max, bbox_y_max,
                    tile_bbox_x_min, tile_bbox_y_min, tile_bbox_x_max, tile_bbox_y_max
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
                ON CONFLICT (id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    display_name_lower = EXCLUDED.display_name_lower,
                    display_mechanism = EXCLUDED.display_mechanism,
                    display_description = EXCLUDED.display_description,
                    display_savings_label = EXCLUDED.display_savings_label,
                    display_unit_price = EXCLUDED.display_unit_price,
                    unit_price_value = EXCLUDED.unit_price_value,
                    unit_price_unit = EXCLUDED.unit_price_unit,
                    unit_price_quality = EXCLUDED.unit_price_quality,
                    pack_size_value = EXCLUDED.pack_size_value,
                    pack_size_unit = EXCLUDED.pack_size_unit,
                    pack_count = EXCLUDED.pack_count,
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
                    item.unit_price_value,
                    item.unit_price_unit,
                    item.unit_price_quality,
                    item.pack_size_value,
                    item.pack_size_unit,
                    item.pack_count,
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

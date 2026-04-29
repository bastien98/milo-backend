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
from promo_folders_pipelines.coupon_barcode import decode_coupon_barcode
from promo_folders_pipelines.mechanism import (
    ALL_KINDS,
    MechanismKind,
    canonical_label,
    compute_savings,
    display_description,
    display_savings_label,
    infer_original_price,
    infer_promo_price,
    min_purchase_qty,
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

GEMINI_MODEL = "gemini-3.1-flash-lite-preview"
MAX_OUTPUT_TOKENS = 65536
PAGES_PER_BATCH = 1  # Single page per Gemini call for maximum bbox accuracy
MAX_BATCH_BYTES = 1_500_000  # 1.5 MB — split oversized batches into single pages
MAX_RETRIES = 4
RETRY_BASE_DELAY = 5  # seconds, doubles each retry
REQUEST_TIMEOUT = 300  # 5 minutes per Gemini call


R2_PUBLIC_BASE_URL = os.environ.get("R2_PUBLIC_BASE_URL", "")

# ---------------------------------------------------------------------------
# Pydantic schemas for Gemini structured output
# ---------------------------------------------------------------------------
class _BboxSchema(PydanticBaseModel):
    x_min: int = Field(ge=0, le=1000, description="Left edge, 0=left 1000=right")
    y_min: int = Field(ge=0, le=1000, description="Top edge, 0=top 1000=bottom")
    x_max: int = Field(ge=0, le=1000, description="Right edge, 0=left 1000=right")
    y_max: int = Field(ge=0, le=1000, description="Bottom edge, 0=top 1000=bottom")


class _PromoItemSchema(PydanticBaseModel):
    # --- Identity ---
    product_name: str = Field(
        description=(
            "Clean Title Case product label visible on the tile: product + variant + size. "
            "Omit brand when the product is identifiable without it (e.g. 'Chips Explosions Salt & Pepper 150 g'). "
            "Keep brand when essential for identity (e.g. 'Coca-Cola Zero 1,5 L'). "
            "For drinks ALWAYS include volume ('33 cl', '6 x 25 cl', '1,5 L'). No promo text or pricing."
        )
    )
    primary_brand: Optional[str] = Field(
        default=None,
        description=(
            "Most prominent brand on the tile, Title Case ('Coca-Cola', 'Boni Selection', 'Lay\\'s', '365'). "
            "null for truly unbranded / generic assortment tiles."
        ),
    )
    additional_brands: list[str] = Field(
        default_factory=list,
        description=(
            "Other brands listed on the SAME tile when the promo covers multiple brands together "
            "(e.g. 'Coca-Cola, Fanta of Sprite' → additional_brands=['Fanta','Sprite']). Empty list otherwise."
        ),
    )

    # --- Mechanism (canonical, cross-store) ---
    mechanism_kind: Literal[
        "buy_x_get_y_free",
        "second_half_price",
        "second_percent_off",
        "percent_off",
        "percent_off_from_n",
        "euro_off",
        "n_for_euro",
        "price_reduction",
    ] = Field(
        description=(
            "Canonical mechanism type, normalized across stores. "
            "buy_x_get_y_free: '1+1 Gratis', '2+1 Gratis', '12+6 Gratis' (any X+Y counts). "
            "second_half_price: '2e aan halve prijs', '2e halve prijs'. "
            "second_percent_off: '2e aan -50%', '2e tegen -X%', '2e voor -X%'. "
            "percent_off: bare '-25%', 'X% korting' applied to a single item. "
            "percent_off_from_n: '-25% vanaf 2 verpakkingen', '-X% bij aankoop van Y'. "
            "euro_off: '€0.50 korting', '-€1 korting'. "
            "n_for_euro: 'X voor €Y', '3 pour €5'. "
            "price_reduction: just a lower price (or 'Prix Choc' / 'Mega Deal' badge) with no labeled mechanism."
        )
    )
    mechanism_x: Optional[float] = Field(
        default=None,
        description=(
            "First parameter of the mechanism. "
            "buy_x_get_y_free: the X in X+Y (e.g. 1 in '1+1'). "
            "percent_off / percent_off_from_n / second_percent_off: the percentage (25 for '-25%'). "
            "euro_off: the euro amount (0.50 for '€0.50 korting'). "
            "n_for_euro: the quantity (2 for '2 voor €5'). "
            "null for second_half_price and price_reduction."
        ),
    )
    mechanism_y: Optional[float] = Field(
        default=None,
        description=(
            "Second parameter of the mechanism. "
            "buy_x_get_y_free: the Y in X+Y (e.g. 1 in '1+1', 6 in '12+6'). "
            "percent_off_from_n: the minimum qty (2 in 'vanaf 2 verpakkingen'). "
            "n_for_euro: the total euro amount (5.00 in '2 voor €5'). "
            "null for all other kinds."
        ),
    )
    promo_campaign: Optional[str] = Field(
        default=None,
        description=(
            "Store marketing banner printed on the tile, verbatim — 'Bonus', 'Bonus Card', 'Prix Choc', "
            "'Mega Deal', 'Sunday Deal', 'New Deal', 'Extra', 'Extra\\'s'. null when no banner is present."
        ),
    )

    # --- Pricing (visible only) ---
    original_price: Optional[float] = Field(
        default=None,
        ge=0,
        description="Struck-through or 'was' price printed on the tile. null when no original price is visible.",
    )
    promo_price: Optional[float] = Field(
        default=None,
        ge=0,
        description="Shelf price actually printed on the tile (price per item or per pack as shown). null if no price is printed (e.g. weighed goods sold per-kg with no unit price).",
    )
    stated_savings: Optional[float] = Field(
        default=None,
        ge=0,
        description="Savings amount explicitly printed on the tile (e.g. 'Bespaar €3.00'). null when not stated.",
    )

    # --- Pack size (visible tokens; Python computes unit price from these) ---
    pack_size_value: Optional[float] = Field(
        default=None, ge=0,
        description="Numeric size of ONE unit as printed. '500 g'→500, '1,5 L'→1.5, '6 x 25 cl'→25. Comma→dot. null if no size visible.",
    )
    pack_size_unit: Optional[Literal['g','kg','ml','cl','l','stuk','rol','doekje','capsule','tab','zakje']] = Field(
        default=None,
        description="Unit of pack_size_value EXACTLY as implied on the page, lowercased. Countables→'stuk', rollen→'rol', tea bags→'zakje', tabs→'tab', capsules→'capsule', wipes→'doekje'. Do NOT convert.",
    )
    pack_count: int = Field(
        default=1, ge=1,
        description="Number of individual units in the pack. '6 x 25 cl'→6, '24 blikjes 33 cl'→24, '4-pack 6 rollen'→4. Default 1.",
    )

    # --- Category (granular taxonomy; Python derives a parent-level consumer category) ---
    granular_category: str = Field(
        description="Pick the single best granular category from the provided list. Use 'Other' if none fit."
    )

    # --- Verbatim tile text, reformatted as Markdown. Rules live in the system prompt. ---
    promo_text_markdown: Optional[str] = Field(
        default=None,
        description="All printed text on the tile, reformatted as Markdown per the VERBATIM PROMO TEXT rules.",
    )

    # --- Search enrichment (rules live in the SEARCH ENRICHMENT system prompt section) ---
    search_text: Optional[str] = Field(
        default=None,
        description="Multilingual search blob per the SEARCH ENRICHMENT rules.",
    )
    generic_product_type: Optional[str] = Field(
        default=None,
        description="Generic English product noun per the SEARCH ENRICHMENT rules.",
    )

    # --- Geometry (mandatory on every item; see GEOMETRY section of the system prompt) ---
    bbox: _BboxSchema = Field(
        description=(
            "Product-only bounding box: tight rectangle around the physical product packaging. "
            "Integer coords 0-1000 (0=left/top, 1000=right/bottom). "
            "See the GEOMETRY section of the system prompt for sizing and exclusion rules."
        ),
    )
    tile_bbox: _BboxSchema = Field(
        description=(
            "Whole-promo-block bounding box: rectangle around every visual element of this offer "
            "(product photo, name, all price labels, mechanism/badge, descriptive text, coloured background). "
            "Must fully contain `bbox`. Integer coords 0-1000 (0=left/top, 1000=right/bottom). "
            "See the GEOMETRY section of the system prompt for the exact element list, outward-expansion "
            "rule, and overlap policy."
        ),
    )

    # --- Coupon detection (see COUPON DETECTION section of the system prompt) ---
    is_coupon: bool = Field(
        default=False,
        description=(
            "TRUE only if this tile is a loyalty-card coupon: loyalty badge + 1D barcode with printed digits "
            "+ redemption fine print, all present together. Product-packaging EANs and QR codes don't qualify."
        ),
    )
    coupon_type: Optional[Literal["loyalty_points", "cashback", "free_product", "percent_off_coupon", "other"]] = Field(
        default=None,
        description=(
            "Reward type of the coupon. loyalty_points: X Bonuspunten / Plus-punten. "
            "cashback: €X korting / €X réduction. free_product: 1 product gratis. "
            "percent_off_coupon: -X% on purchase. other: clearly a coupon but none of the above fit. "
            "null when is_coupon is false."
        ),
    )
    coupon_value: Optional[float] = Field(
        default=None,
        description=(
            "Numeric reward: points count for loyalty_points, euro amount for cashback, "
            "percent for percent_off_coupon. null for free_product, other, or when is_coupon is false."
        ),
    )
    coupon_min_purchase: Optional[str] = Field(
        default=None,
        description=(
            "Verbatim trigger condition printed on the coupon "
            "(e.g. '1 pot Natù-fruitspread', '€20 aan Nivea', '2 producten van Prince'). "
            "null when is_coupon is false or no trigger is printed."
        ),
    )
    coupon_validity_end: Optional[date] = Field(
        default=None,
        description=(
            "Coupon's own 'Geldig tot DD/MM/YYYY' / 'Valable jusqu'au' end date in YYYY-MM-DD. "
            "null when the coupon relies on the folder's global validity, or when is_coupon is false."
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
    cache_name: Optional[str] = None,
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
            config_kwargs: Dict[str, Any] = dict(
                max_output_tokens=MAX_OUTPUT_TOKENS,
                temperature=0.2,
                thinking_config=types.ThinkingConfig(thinking_level="high"),
                response_mime_type="application/json",
                response_schema=_PromoFolderSchema,
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
            )
            if cache_name:
                config_kwargs["cached_content"] = cache_name
            else:
                config_kwargs["system_instruction"] = system_prompt
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=batch_pdf, mime_type="application/pdf"),
                    f"Extract all promotional product offers from this {display_name} promo folder page.",
                ],
                config=types.GenerateContentConfig(**config_kwargs),
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

        # Stamp every item with the batch's starting page number.
        # Multi-page PDF batches are single-page in practice (PAGES_PER_BATCH = 1).
        for item in data.get("items", []):
            item["page_number"] = start_page

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
    cache_name: Optional[str] = None,
) -> dict:
    """Extract promo items from a batch of page images via Gemini structured output.

    Args:
        images: List of (page_number, webp_bytes) tuples (1-indexed page numbers)
        batch_num: Batch sequence number for logging
    """
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

        # Slightly higher entropy than greedy (0.0) to avoid deterministic truncation /
        # skipping loops on dense pages; bumped further on retries.
        temp = 0.2 if attempt == 1 else 0.4

        try:
            config_kwargs: Dict[str, Any] = dict(
                max_output_tokens=MAX_OUTPUT_TOKENS,
                temperature=temp,
                thinking_config=types.ThinkingConfig(thinking_level="high"),
                response_mime_type="application/json",
                response_schema=_PromoFolderSchema,
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
            )
            if cache_name:
                config_kwargs["cached_content"] = cache_name
            else:
                config_kwargs["system_instruction"] = system_prompt
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=parts,
                config=types.GenerateContentConfig(**config_kwargs),
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

        # Batches are 1 page (PAGES_PER_BATCH = 1); stamp every item with the
        # batch's absolute page number instead of asking Gemini to emit it.
        first_page = page_nums[0]
        for item in data.get("items", []):
            item["page_number"] = first_page

        item_count = len(data.get("items", []))
        logger.info(f"{label} Done in {elapsed:.1f}s — {item_count} items extracted")
        return data

    return {"items": []}


def _create_extraction_cache(
    client: genai.Client, system_prompt: str, label: str = ""
) -> Optional[str]:
    """Cache the extraction system prompt for the duration of a pipeline run.

    Returns the cache resource name, or None if creation failed (caller falls
    back to inline `system_instruction`, which still works but pays full price
    on every page).
    """
    try:
        cache = client.caches.create(
            model=GEMINI_MODEL,
            config=types.CreateCachedContentConfig(
                system_instruction=system_prompt,
                ttl="3600s",
            ),
        )
        logger.info(f"{label} Created extraction cache {cache.name} (TTL 1h)")
        return cache.name
    except Exception as e:
        logger.warning(f"{label} Cache creation failed, falling back to inline prompt: {e}")
        return None


def _delete_cache(client: genai.Client, cache_name: Optional[str], label: str = "") -> None:
    if not cache_name:
        return
    try:
        client.caches.delete(name=cache_name)
        logger.info(f"{label} Deleted cache {cache_name}")
    except Exception as e:
        logger.warning(f"{label} Cache deletion failed (will expire by TTL): {e}")


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


def _resolve_tile_overlaps(
    items_on_page: list[dict],
    label: str,
    max_iters: int = 20,
) -> None:
    """Mutate `tile_bbox`es in place so no two items overlap.

    For each overlapping pair we split the encroachment along the shorter overlap
    axis, area-weighted: the larger box gives up proportionally more, so small
    tiles are protected from being shrunk into nothing. Iterates until no
    pairwise overlap remains or `max_iters` is reached. Inner `bbox`es are
    re-clipped to the (possibly shrunken) tile to preserve containment.
    """
    tiles = [(i, item) for i, item in enumerate(items_on_page) if item.get("tile_bbox")]
    if len(tiles) < 2:
        return

    initial_overlaps = 0
    for ai in range(len(tiles)):
        a = tiles[ai][1]["tile_bbox"]
        for bi in range(ai + 1, len(tiles)):
            b = tiles[bi][1]["tile_bbox"]
            if min(a["x_max"], b["x_max"]) > max(a["x_min"], b["x_min"]) and \
               min(a["y_max"], b["y_max"]) > max(a["y_min"], b["y_min"]):
                initial_overlaps += 1

    if initial_overlaps == 0:
        return

    converged_in = None
    for iteration in range(1, max_iters + 1):
        any_overlap = False
        for ai in range(len(tiles)):
            for bi in range(ai + 1, len(tiles)):
                a = tiles[ai][1]["tile_bbox"]
                b = tiles[bi][1]["tile_bbox"]
                ix1 = max(a["x_min"], b["x_min"])
                iy1 = max(a["y_min"], b["y_min"])
                ix2 = min(a["x_max"], b["x_max"])
                iy2 = min(a["y_max"], b["y_max"])
                ow = ix2 - ix1
                oh = iy2 - iy1
                if ow <= 0 or oh <= 0:
                    continue
                any_overlap = True

                area_a = (a["x_max"] - a["x_min"]) * (a["y_max"] - a["y_min"])
                area_b = (b["x_max"] - b["x_min"]) * (b["y_max"] - b["y_min"])
                total = area_a + area_b
                if total <= 0:
                    continue
                share_a = area_a / total
                share_b = area_b / total

                if ow <= oh:
                    delta_a = max(1, round(ow * share_a))
                    delta_b = max(1, round(ow * share_b))
                    a_center = a["x_min"] + a["x_max"]
                    b_center = b["x_min"] + b["x_max"]
                    if a_center < b_center:
                        a["x_max"] = max(a["x_min"] + 1, a["x_max"] - delta_a)
                        b["x_min"] = min(b["x_max"] - 1, b["x_min"] + delta_b)
                    else:
                        a["x_min"] = min(a["x_max"] - 1, a["x_min"] + delta_a)
                        b["x_max"] = max(b["x_min"] + 1, b["x_max"] - delta_b)
                else:
                    delta_a = max(1, round(oh * share_a))
                    delta_b = max(1, round(oh * share_b))
                    a_center = a["y_min"] + a["y_max"]
                    b_center = b["y_min"] + b["y_max"]
                    if a_center < b_center:
                        a["y_max"] = max(a["y_min"] + 1, a["y_max"] - delta_a)
                        b["y_min"] = min(b["y_max"] - 1, b["y_min"] + delta_b)
                    else:
                        a["y_min"] = min(a["y_max"] - 1, a["y_min"] + delta_a)
                        b["y_max"] = max(b["y_min"] + 1, b["y_max"] - delta_b)

        if not any_overlap:
            converged_in = iteration
            break

    if converged_in is not None:
        logger.info(
            f"{label} Resolved {initial_overlaps} tile_bbox overlap(s) "
            f"in {converged_in} iteration(s)"
        )
    else:
        logger.warning(
            f"{label} Tile overlap resolver hit max_iters={max_iters}; "
            f"started with {initial_overlaps} overlapping pair(s) — some may remain"
        )

    # Re-enforce containment: a shrunken tile may no longer enclose its product bbox.
    for _, item in tiles:
        tile = item["tile_bbox"]
        bbox = item.get("bbox")
        if bbox and not _contains(tile, bbox):
            clipped = _clip_to(bbox, tile)
            if clipped["x_max"] > clipped["x_min"] and clipped["y_max"] > clipped["y_min"]:
                item["bbox"] = clipped
            else:
                item["bbox"] = dict(tile)

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

    # Build the item list for the validation prompt. Every item goes through review.
    item_descriptions = []
    for i, item in enumerate(items_on_page):
        name = item.get("display_name") or item.get("product_name", "Unknown")
        tile_bbox = item.get("tile_bbox")
        bbox = item.get("bbox")

        tile_str = f"[{tile_bbox['x_min']}, {tile_bbox['y_min']}, {tile_bbox['x_max']}, {tile_bbox['y_max']}]" if tile_bbox else "null (LOCATE THIS ITEM)"
        bbox_str = f"[{bbox['x_min']}, {bbox['y_min']}, {bbox['x_max']}, {bbox['y_max']}]" if bbox else "null"

        item_descriptions.append(f"{i}. [REVIEW — check and correct if wrong] \"{name}\" — tile_bbox: {tile_str}, bbox: {bbox_str}")

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

            orig_tile = items_on_page[idx].get("tile_bbox")
            orig_bbox = items_on_page[idx].get("bbox")

            # Asymmetric IoU threshold: looser bar when the original bbox looks geometrically suspect.
            tile_threshold = (
                IOU_REJECT_THRESHOLD_SUSPECT
                if _is_suspect_original(orig_tile, None)
                else IOU_REJECT_THRESHOLD
            )
            bbox_threshold = (
                IOU_REJECT_THRESHOLD_SUSPECT
                if _is_suspect_original(orig_bbox, None)
                else IOU_REJECT_THRESHOLD
            )

            # tile_bbox: reject drastic corrections, keep original on null regression
            new_tile = vi.get("tile_bbox")
            if new_tile and isinstance(new_tile, dict):
                if orig_tile:
                    iou = _iou(orig_tile, new_tile)
                    if iou < tile_threshold:
                        logger.warning(
                            f"{label} Rejecting tile_bbox correction for item {idx}: IoU={iou:.2f} "
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
                            f"{label} Rejecting bbox correction for item {idx}: IoU={iou:.2f} "
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
            f"{label} Validation: {confirmed} confirmed, {corrected} corrected, {added} added"
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

    cache_name = _create_extraction_cache(client, system_prompt, f"[{display_name}]")
    try:
        for i, batch in enumerate(batches):
            data = extract_batch_images(
                client, batch, i + 1, system_prompt, display_name, cache_name=cache_name
            )
            if data.get("validity_start") and not validity_start:
                validity_start = data["validity_start"]
                validity_end = data.get("validity_end")
            all_items.extend(data.get("items", []))

        elapsed = time.time() - start_time
        logger.info(f"All batches complete in {elapsed:.1f}s — {len(all_items)} total items")

        # Optional second-pass bbox validation. Disabled by default; opt in per
        # store via `validate_bboxes: true` in the YAML config.
        if config.get("validate_bboxes", False) and all_items:
            logger.info("Starting bbox validation pass...")
            validation_start = time.time()

            image_lookup = {num: img for num, img in page_images}

            from collections import defaultdict
            items_by_page: dict[int, list[tuple[int, dict]]] = defaultdict(list)
            for idx, item in enumerate(all_items):
                pn = item.get("page_number")
                if pn is not None:
                    items_by_page[pn].append((idx, item))

            for pn, indexed_items in sorted(items_by_page.items()):
                page_img = image_lookup.get(pn)
                if not page_img:
                    logger.warning(
                        f"No image found for page {pn} — skipping bbox validation "
                        f"for {len(indexed_items)} item(s)"
                    )
                    continue

                page_items = [item for _, item in indexed_items]
                validated = validate_page_bboxes(client, page_img, pn, page_items, display_name)
                _resolve_tile_overlaps(validated, f"[{display_name} p{pn} resolve]")

                for (orig_idx, _), new_item in zip(indexed_items, validated):
                    all_items[orig_idx] = new_item

            validation_elapsed = time.time() - validation_start
            logger.info(f"Bbox validation complete in {validation_elapsed:.1f}s")
    finally:
        _delete_cache(client, cache_name, f"[{display_name}]")

    return {
        "validity_start": validity_start,
        "validity_end": validity_end,
        "items": all_items,
    }


def extract_promos_from_pdf(
    pdf_data: bytes,
    config: Dict[str, Any],
    page_filter: Optional[int] = None,
) -> dict:
    """Split PDF into batches and extract promo items sequentially.

    Args:
        page_filter: When set, only extract from this 1-indexed page number.
            Other pages are skipped so the cost of iterating on one bad page
            stays bounded.
    """
    batches = split_pdf_into_batches(pdf_data)
    if page_filter is not None:
        batches = [(pdf, sp) for pdf, sp in batches if sp == page_filter]
        if not batches:
            logger.warning(
                f"--page {page_filter} requested but PDF has no batch starting on that page"
            )
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

    cache_name = _create_extraction_cache(client, system_prompt, f"[{display_name}]")
    try:
        for i, (batch_pdf, start_page) in enumerate(batches):
            data = extract_batch(
                client, batch_pdf, i + 1, start_page, system_prompt, display_name, cache_name=cache_name
            )
            if data.get("validity_start") and not validity_start:
                validity_start = data["validity_start"]
                validity_end = data.get("validity_end")
            all_items.extend(data.get("items", []))

        elapsed = time.time() - start_time
        logger.info(f"All batches complete in {elapsed:.1f}s — {len(all_items)} total items")
    finally:
        _delete_cache(client, cache_name, f"[{display_name}]")

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

    Gemini emits only the perceptual signal; this function derives every display
    string and numeric field via `mechanism.py`.
    """
    validity_start = data.get("validity_start")
    validity_end = data.get("validity_end")
    if not validity_start or not validity_end:
        raise ValueError("Promo folder extraction is missing validity_start or validity_end")

    items: list[PromoItem] = []
    skipped = 0
    raw_items = data.get("items", [])
    logger.info(f"Parsing {len(raw_items)} raw items from Gemini output")

    for raw in raw_items:
        product_name = (raw.get("product_name") or raw.get("display_name") or "").strip()
        if not product_name:
            logger.warning("Skipping item with empty product_name")
            skipped += 1
            continue

        # --- Brand ---
        primary_brand = (raw.get("primary_brand") or "").strip() or None
        additional_brands_raw = raw.get("additional_brands") or []
        if isinstance(additional_brands_raw, str):
            additional_brands_raw = [additional_brands_raw]
        additional_brands = [b.strip() for b in additional_brands_raw if isinstance(b, str) and b.strip()]

        # --- Mechanism (canonical) ---
        kind = (raw.get("mechanism_kind") or "price_reduction").strip()
        if kind not in ALL_KINDS:
            logger.warning(f"Item '{product_name}': unknown mechanism_kind {kind!r}, defaulting to price_reduction")
            kind = "price_reduction"
        mechanism_x = _parse_price(raw.get("mechanism_x"))
        mechanism_y = _parse_price(raw.get("mechanism_y"))
        promo_campaign = (raw.get("promo_campaign") or "").strip() or None

        # --- Pricing: visible values, then reverse-infer missing ones ---
        original_price = _parse_price(raw.get("original_price"))
        promo_price = _parse_price(raw.get("promo_price"))
        stated_savings = _parse_price(raw.get("stated_savings"))

        if original_price is None and promo_price is not None:
            original_price = infer_original_price(kind, mechanism_x, mechanism_y, promo_price, stated_savings)
        if promo_price is None and original_price is not None:
            promo_price = infer_promo_price(kind, mechanism_x, mechanism_y, original_price)

        if original_price is None and promo_price is None:
            logger.warning(f"Item '{product_name}' (p{raw.get('page_number')}): no pricing extracted")

        original_price = round(original_price, 2) if original_price is not None else None
        promo_price = round(promo_price, 2) if promo_price is not None else None
        stated_savings = round(stated_savings, 2) if stated_savings is not None else None

        # --- Derived fields ---
        min_qty = min_purchase_qty(kind, mechanism_x, mechanism_y)
        savings = compute_savings(kind, mechanism_x, mechanism_y, original_price, promo_price, stated_savings)
        savings_amount = round(savings, 2) if savings is not None else 0.0

        depth_original = original_price if original_price is not None else promo_price
        promo_depth = (
            compute_promo_depth(savings_amount, depth_original, min_qty)
            if depth_original and depth_original > 0 else 0.0
        )

        display_mechanism = canonical_label(kind, mechanism_x, mechanism_y)
        dsc = display_description(kind, mechanism_x, mechanism_y)
        dsl = display_savings_label(kind, mechanism_x, mechanism_y, savings)

        # --- Category: Gemini emits granular; Python derives the parent consumer bucket ---
        granular = (raw.get("granular_category") or "Other").strip()
        if granular not in GRANULAR_CATEGORIES:
            logger.warning(f"Item '{product_name}': unknown granular_category {granular!r}, defaulting to 'Other'")
            granular = "Other"
        parent_category = get_parent_category(granular)

        # --- Pack size tokens ---
        pack_size_value = _parse_price(raw.get("pack_size_value"))
        pack_size_unit = (raw.get("pack_size_unit") or "").strip().lower() or None
        pack_count = max(1, int(raw.get("pack_count") or 1))

        unit_price = compute_unit_price(
            promo_price=promo_price if promo_price is not None else 0.0,
            original_price=original_price if original_price is not None else (promo_price or 0.0),
            min_purchase_qty=min_qty,
            savings_amount=savings_amount,
            pack_size_value=pack_size_value,
            pack_size_unit=pack_size_unit,
            pack_count=pack_count,
            display_name=product_name,
            granular_category=granular,
        )

        mismatch = validate_pack_size(product_name, pack_size_value, pack_size_unit)
        if mismatch:
            logger.warning(f"Item '{product_name}' (p{raw.get('page_number')}): {mismatch}")
        for warn in unit_price.warnings:
            logger.info(f"Item '{product_name}' (p{raw.get('page_number')}): unit-price {warn}")

        # --- Geometry: normalize 0-1000 ints to 0-1 floats ---
        bbox_dict = _normalize_bbox(raw.get("bbox"))
        tile_bbox_dict = _normalize_bbox(raw.get("tile_bbox"))
        if not tile_bbox_dict:
            logger.warning(f"Item '{product_name}' (p{raw.get('page_number')}): missing tile_bbox")
        if not bbox_dict:
            logger.debug(f"Item '{product_name}' (p{raw.get('page_number')}): no product bbox")

        # Coupon fields (Gemini-extracted; barcode decoding happens later, in the crop step).
        is_coupon = bool(raw.get("is_coupon", False))
        coupon_type = raw.get("coupon_type") if is_coupon else None
        coupon_value = _parse_price(raw.get("coupon_value")) if is_coupon else None
        coupon_min_purchase = raw.get("coupon_min_purchase") if is_coupon else None
        coupon_validity_end = raw.get("coupon_validity_end") if is_coupon else None

        items.append(
            PromoItem(
                display_name=product_name,
                primary_brand=primary_brand,
                additional_brands=additional_brands,
                display_mechanism=display_mechanism,
                display_description=dsc,
                display_savings_label=dsl,
                display_unit_price=unit_price.display_unit_price,
                mechanism_kind=kind,
                mechanism_x=mechanism_x,
                mechanism_y=mechanism_y,
                promo_campaign=promo_campaign,
                original_price=original_price,
                promo_price=promo_price,
                stated_savings=stated_savings,
                savings_amount=savings_amount,
                min_purchase_qty=min_qty,
                promo_depth=promo_depth,
                unit_price_value=unit_price.unit_price_value,
                unit_price_unit=unit_price.unit_price_unit,
                unit_price_quality=unit_price.quality,
                pack_size_value=pack_size_value,
                pack_size_unit=pack_size_unit,
                pack_count=pack_count,
                granular_category=granular,
                category=parent_category,
                promo_text_markdown=raw.get("promo_text_markdown"),
                search_text=_clean_search_text(raw.get("search_text")),
                generic_product_type=_clean_generic_product_type(raw.get("generic_product_type")),
                validity_start=validity_start,
                validity_end=validity_end,
                source_retailer=store_id,
                source_type="folder",
                page_number=raw.get("page_number"),
                promo_folder_url=promo_folder_url,
                bbox=bbox_dict,
                tile_bbox=tile_bbox_dict,
                is_coupon=is_coupon,
                coupon_type=coupon_type,
                coupon_value=coupon_value,
                coupon_min_purchase=coupon_min_purchase,
                coupon_validity_end=coupon_validity_end,
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


def _clean_search_text(val: Any) -> Optional[str]:
    """Normalize Gemini's search_text: lowercase, unaccent, collapse whitespace.

    Gemini is asked to emit the blob in this format already, but we enforce
    it here so the trgm index sees uniform values regardless of model drift.
    """
    if not val or not isinstance(val, str):
        return None
    import unicodedata
    s = unicodedata.normalize("NFD", val.strip().lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"\s+", " ", s)
    return s[:512] or None


def _clean_generic_product_type(val: Any) -> Optional[str]:
    if not val or not isinstance(val, str):
        return None
    s = val.strip().lower()
    return s[:64] or None


def _normalize_bbox(raw: Optional[dict]) -> Optional[dict]:
    """Convert Gemini's 0-1000 integer bbox to our 0-1 float storage format."""
    if not raw or not isinstance(raw, dict):
        return None
    x_min = raw.get("x_min")
    y_min = raw.get("y_min")
    x_max = raw.get("x_max")
    y_max = raw.get("y_max")
    if None in (x_min, y_min, x_max, y_max):
        return None
    if x_min >= x_max or y_min >= y_max:
        return None
    return {
        "x_min": x_min / 1000.0,
        "y_min": y_min / 1000.0,
        "x_max": x_max / 1000.0,
        "y_max": y_max / 1000.0,
    }


def generate_record_id(item: PromoItem) -> str:
    """Generate a deterministic ID for a promo item.

    Includes page_number and tile_bbox coordinates so same-name variants on the
    same page (e.g. "Kipfilet" 600g vs 1kg) produce distinct IDs and don't
    collapse under ON CONFLICT (id) DO UPDATE during upsert.
    """
    tb = item.tile_bbox or {}
    tile_sig = (
        f"{tb.get('x_min','')}:{tb.get('y_min','')}:"
        f"{tb.get('x_max','')}:{tb.get('y_max','')}"
    )
    key = (
        f"{item.source_retailer}:{item.display_name}:"
        f"{item.page_number}:{tile_sig}:"
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


def _crop_from_normalized_bbox(
    page_img: Image.Image, bbox: dict, min_area: float = 0.0025, min_px: int = 64
) -> Optional[Image.Image]:
    """Crop a page image using 0-1 normalized coords. Returns None if invalid."""
    x_min = bbox.get("x_min", 0)
    y_min = bbox.get("y_min", 0)
    x_max = bbox.get("x_max", 0)
    y_max = bbox.get("y_max", 0)

    if x_min >= x_max or y_min >= y_max:
        return None
    if (x_max - x_min) * (y_max - y_min) < min_area:
        return None

    pw, ph = page_img.size
    x1 = max(0, int(x_min * pw))
    y1 = max(0, int(y_min * ph))
    x2 = min(pw, int(x_max * pw))
    y2 = min(ph, int(y_max * ph))

    if (x2 - x1) < min_px or (y2 - y1) < min_px:
        return None

    return page_img.crop((x1, y1, x2, y2))


def crop_and_upload_item_images(
    items: list[PromoItem],
    page_images: dict[int, bytes],
    r2: R2PromoStorage,
    store_id: str,
    folder_index: int = 1,
) -> None:
    """Crop each item's product and full-tile images from pages and upload to R2.

    Produces two crop sets per item:
      - Product crop (from `bbox`, padded to square): thumb.webp (200px), medium.webp (400px)
        → thumbnail_url, image_url. Used in carousels and minimal tile views.
      - Full-tile crop (from `tile_bbox`, natural aspect): tile.webp (800px)
        → hero_url. Used in the iOS product-detail view to show the whole promo tile
        (product + price label + brand + badge + background).

    Items without a valid `bbox` are skipped. `tile_bbox` is best-effort; if missing
    or invalid, hero_url stays None.
    """
    if not R2_PUBLIC_BASE_URL:
        logger.warning("R2_PUBLIC_BASE_URL not set — skipping image upload")
        return

    product_uploaded = 0
    tile_uploaded = 0
    skipped_no_bbox = 0
    skipped_invalid = 0
    tile_missing = 0

    for item in items:
        if not item.bbox:
            skipped_no_bbox += 1
            continue

        page_num = item.page_number
        if not page_num or page_num not in page_images:
            skipped_invalid += 1
            continue

        try:
            page_img = Image.open(io.BytesIO(page_images[page_num])).convert("RGB")
        except Exception as e:
            logger.warning(f"Could not open page {page_num} image: {e}")
            skipped_invalid += 1
            continue

        # Product crop — tight around the product, padded to square for uniform
        # display in iOS grids. The extraction prompt already leaves a 2-3% margin,
        # so no extra pre-crop padding is needed here.
        product_crop = _crop_from_normalized_bbox(page_img, item.bbox)
        if product_crop is None:
            skipped_invalid += 1
            continue
        product_crop = _pad_to_square(product_crop)

        record_id = generate_record_id(item)
        base_key = f"promo_item_images/{store_id}/{record_id}"

        try:
            for size, suffix in ((200, "thumb"), (400, "medium")):
                resized = _resize_to_max(product_crop, size)
                buf = io.BytesIO()
                resized.save(buf, format="WEBP", quality=85)
                r2.upload_image(f"{base_key}/{suffix}.webp", buf.getvalue())

            item.thumbnail_url = f"{R2_PUBLIC_BASE_URL}/{base_key}/thumb.webp"
            item.image_url = f"{R2_PUBLIC_BASE_URL}/{base_key}/medium.webp"
            product_uploaded += 1
        except Exception as e:
            logger.warning(f"Product image upload failed for '{item.display_name}': {e}")
            continue

        # Tile crop — full promo tile, natural aspect (no square padding).
        # Powers the iOS product-detail view.
        if not item.tile_bbox:
            tile_missing += 1
            continue
        tile_crop = _crop_from_normalized_bbox(page_img, item.tile_bbox)
        if tile_crop is None:
            tile_missing += 1
            continue

        try:
            resized_tile = _resize_to_max(tile_crop, 800)
            buf = io.BytesIO()
            resized_tile.save(buf, format="WEBP", quality=85)
            r2.upload_image(f"{base_key}/tile.webp", buf.getvalue())
            item.hero_url = f"{R2_PUBLIC_BASE_URL}/{base_key}/tile.webp"
            tile_uploaded += 1
        except Exception as e:
            logger.warning(f"Tile image upload failed for '{item.display_name}': {e}")

        # --- Coupon barcode decoding ---
        # Only attempt decode when Gemini classified this tile as a coupon. We rely on
        # the semantic classifier to rule out product-packaging EANs that happen to be
        # visible inside the tile.
        if item.is_coupon:
            try:
                decoded = decode_coupon_barcode(
                    tile_crop=tile_crop,
                    tile_bbox_page_normalized=item.tile_bbox,
                    page_size=page_img.size,
                )
                if decoded is not None:
                    item.coupon_barcode_value = decoded.value
                    item.coupon_barcode_format = decoded.barcode_format
                    item.barcode_bbox = decoded.bbox_page_normalized
                else:
                    logger.warning(
                        f"Coupon barcode decode failed for '{item.display_name}' "
                        f"(p{item.page_number}, store={store_id}) — coupon will be "
                        f"displayable but unscannable"
                    )
            except Exception as e:
                logger.warning(f"Coupon decode errored for '{item.display_name}': {e}")

    coupon_count = sum(1 for i in items if i.is_coupon)
    coupon_decoded = sum(1 for i in items if i.is_coupon and i.coupon_barcode_value)
    logger.info(
        f"Item images: {product_uploaded} product crops, {tile_uploaded} tile crops uploaded; "
        f"{skipped_no_bbox} skipped (no bbox), "
        f"{skipped_invalid} skipped (invalid bbox/page), "
        f"{tile_missing} tile crops skipped (missing/invalid tile_bbox); "
        f"coupons: {coupon_decoded}/{coupon_count} barcodes decoded"
    )


# ---------------------------------------------------------------------------
# Manual bbox overrides (promo_item_bbox_overrides table)
# ---------------------------------------------------------------------------
def _normalize_override_name(name: str) -> str:
    """Canonicalize a display_name for override lookup: lowercase + strip.

    Must match the SQL expression `LOWER(TRIM(display_name))` used when we live-patch
    promo_items rows from set_bbox_override.py, so the two lookup paths agree.
    """
    return name.lower().strip() if name else ""


def fetch_bbox_overrides(promo_folder_url: str) -> dict[tuple[int, str], dict]:
    """Load the override rows for a folder into a {(page, name_norm): {tile, bbox}} dict.

    Separated from `apply_bbox_overrides` so the apply logic stays pure and testable.
    """
    import psycopg2

    conn = psycopg2.connect(_get_pg_connection_string())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT page_number, display_name_normalized,
                   tile_bbox_x_min, tile_bbox_y_min, tile_bbox_x_max, tile_bbox_y_max,
                   bbox_x_min, bbox_y_min, bbox_x_max, bbox_y_max
              FROM promo_item_bbox_overrides
             WHERE promo_folder_url = %s
            """,
            (promo_folder_url,),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    overrides: dict[tuple[int, str], dict] = {}
    for row in rows:
        page, name_norm, tx_min, ty_min, tx_max, ty_max, bx_min, by_min, bx_max, by_max = row
        tile = {
            "x_min": float(tx_min),
            "y_min": float(ty_min),
            "x_max": float(tx_max),
            "y_max": float(ty_max),
        }
        if None not in (bx_min, by_min, bx_max, by_max):
            bbox = {
                "x_min": float(bx_min),
                "y_min": float(by_min),
                "x_max": float(bx_max),
                "y_max": float(by_max),
            }
        else:
            bbox = dict(tile)
        overrides[(int(page), name_norm)] = {"tile_bbox": tile, "bbox": bbox}
    return overrides


def _apply_overrides_to_items(
    items: list[PromoItem],
    overrides: dict[tuple[int, str], dict],
) -> int:
    """Pure apply step — mutates items in place. Returns count applied."""
    if not items or not overrides:
        return 0
    applied = 0
    for item in items:
        if item.page_number is None:
            continue
        key = (item.page_number, _normalize_override_name(item.display_name))
        override = overrides.get(key)
        if override is None:
            continue
        item.tile_bbox = dict(override["tile_bbox"])
        item.bbox = dict(override["bbox"])
        applied += 1
        logger.info(
            f"Applied bbox override: p{item.page_number} '{item.display_name}' "
            f"tile={item.tile_bbox}"
        )
    return applied


def apply_bbox_overrides(
    items: list[PromoItem],
    promo_folder_url: Optional[str],
) -> int:
    """Overwrite `bbox` and `tile_bbox` on items that match a row in promo_item_bbox_overrides.

    The override table is the 100% guarantee: once a box is manually corrected for a
    (folder_url, page, display_name) triple it stays correct across every re-ingest.

    When the override's `bbox_*` columns are NULL, `bbox` falls back to the overridden
    tile_bbox. Unmatched items are left untouched.

    Returns the number of items whose bboxes were replaced.
    """
    if not items or not promo_folder_url:
        return 0
    overrides = fetch_bbox_overrides(promo_folder_url)
    applied = _apply_overrides_to_items(items, overrides)
    if applied:
        logger.info(f"Applied {applied} bbox override(s) for folder {promo_folder_url}")
    return applied


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
    from psycopg2.extras import Json

    seen_ids: dict[str, PromoItem] = {}
    for item in items:
        rid = generate_record_id(item)
        if rid in seen_ids:
            prev = seen_ids[rid]
            logger.warning(
                "ID COLLISION during upsert — dropping duplicate. "
                "id=%s retailer=%s page=%s names=(%r, %r) tile_bboxes=(%s, %s)",
                rid, item.source_retailer, item.page_number,
                prev.display_name, item.display_name,
                prev.tile_bbox, item.tile_bbox,
            )
            continue
        seen_ids[rid] = item

    conn = psycopg2.connect(_get_pg_connection_string())
    try:
        cur = conn.cursor()
        for record_id, item in seen_ids.items():
            # Extract bbox coordinates (None if bbox is missing)
            bbox = item.bbox or {}
            tile = item.tile_bbox or {}

            barcode_bbox = item.barcode_bbox or {}

            cur.execute(
                """
                INSERT INTO promo_items (
                    id, display_name, display_name_lower, display_mechanism,
                    display_description, display_savings_label, display_unit_price,
                    mechanism_kind, mechanism_x, mechanism_y, promo_campaign,
                    unit_price_value, unit_price_unit, unit_price_quality,
                    pack_size_value, pack_size_unit, pack_count,
                    normalized_brand, display_brand, primary_brand, additional_brands,
                    original_price, promo_price, stated_savings, savings_amount,
                    min_purchase_qty, promo_depth,
                    granular_category, category,
                    source_retailer, source_type,
                    page_number, promo_folder_url, validity_start, validity_end,
                    thumbnail_url, image_url, hero_url,
                    bbox_x_min, bbox_y_min, bbox_x_max, bbox_y_max,
                    tile_bbox_x_min, tile_bbox_y_min, tile_bbox_x_max, tile_bbox_y_max,
                    promo_text_markdown,
                    search_text, generic_product_type,
                    is_coupon, coupon_type, coupon_barcode_value, coupon_barcode_format,
                    coupon_value, coupon_min_purchase, coupon_validity_end,
                    barcode_bbox_x_min, barcode_bbox_y_min, barcode_bbox_x_max, barcode_bbox_y_max
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s,
                    %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s
                )
                ON CONFLICT (id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    display_name_lower = EXCLUDED.display_name_lower,
                    display_mechanism = EXCLUDED.display_mechanism,
                    display_description = EXCLUDED.display_description,
                    display_savings_label = EXCLUDED.display_savings_label,
                    display_unit_price = EXCLUDED.display_unit_price,
                    mechanism_kind = EXCLUDED.mechanism_kind,
                    mechanism_x = EXCLUDED.mechanism_x,
                    mechanism_y = EXCLUDED.mechanism_y,
                    promo_campaign = EXCLUDED.promo_campaign,
                    unit_price_value = EXCLUDED.unit_price_value,
                    unit_price_unit = EXCLUDED.unit_price_unit,
                    unit_price_quality = EXCLUDED.unit_price_quality,
                    pack_size_value = EXCLUDED.pack_size_value,
                    pack_size_unit = EXCLUDED.pack_size_unit,
                    pack_count = EXCLUDED.pack_count,
                    normalized_brand = EXCLUDED.normalized_brand,
                    display_brand = EXCLUDED.display_brand,
                    primary_brand = EXCLUDED.primary_brand,
                    additional_brands = EXCLUDED.additional_brands,
                    original_price = EXCLUDED.original_price,
                    promo_price = EXCLUDED.promo_price,
                    stated_savings = EXCLUDED.stated_savings,
                    savings_amount = EXCLUDED.savings_amount,
                    min_purchase_qty = EXCLUDED.min_purchase_qty,
                    promo_depth = EXCLUDED.promo_depth,
                    granular_category = EXCLUDED.granular_category,
                    category = EXCLUDED.category,
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
                    tile_bbox_y_max = EXCLUDED.tile_bbox_y_max,
                    promo_text_markdown = EXCLUDED.promo_text_markdown,
                    search_text = EXCLUDED.search_text,
                    generic_product_type = EXCLUDED.generic_product_type,
                    is_coupon = EXCLUDED.is_coupon,
                    coupon_type = EXCLUDED.coupon_type,
                    coupon_barcode_value = EXCLUDED.coupon_barcode_value,
                    coupon_barcode_format = EXCLUDED.coupon_barcode_format,
                    coupon_value = EXCLUDED.coupon_value,
                    coupon_min_purchase = EXCLUDED.coupon_min_purchase,
                    coupon_validity_end = EXCLUDED.coupon_validity_end,
                    barcode_bbox_x_min = EXCLUDED.barcode_bbox_x_min,
                    barcode_bbox_y_min = EXCLUDED.barcode_bbox_y_min,
                    barcode_bbox_x_max = EXCLUDED.barcode_bbox_x_max,
                    barcode_bbox_y_max = EXCLUDED.barcode_bbox_y_max
                """,
                (
                    record_id,
                    item.display_name,
                    item.display_name.lower(),
                    item.display_mechanism,
                    item.display_description,
                    item.display_savings_label,
                    item.display_unit_price,
                    item.mechanism_kind,
                    item.mechanism_x,
                    item.mechanism_y,
                    item.promo_campaign,
                    item.unit_price_value,
                    item.unit_price_unit,
                    item.unit_price_quality,
                    item.pack_size_value,
                    item.pack_size_unit,
                    item.pack_count,
                    item.normalized_brand,
                    item.primary_brand,  # legacy display_brand column now stores the primary brand
                    item.primary_brand,
                    Json(item.additional_brands) if item.additional_brands else None,
                    item.original_price,
                    item.promo_price,
                    item.stated_savings,
                    item.savings_amount,
                    item.min_purchase_qty,
                    item.promo_depth,
                    item.granular_category,
                    item.category,
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
                    item.promo_text_markdown,
                    item.search_text,
                    item.generic_product_type,
                    item.is_coupon,
                    item.coupon_type,
                    item.coupon_barcode_value,
                    item.coupon_barcode_format,
                    item.coupon_value,
                    item.coupon_min_purchase,
                    item.coupon_validity_end,
                    barcode_bbox.get("x_min"),
                    barcode_bbox.get("y_min"),
                    barcode_bbox.get("x_max"),
                    barcode_bbox.get("y_max"),
                ),
            )

        conn.commit()
        cur.close()
    finally:
        conn.close()

    dropped = len(items) - len(seen_ids)
    suffix = f" ({dropped} dropped as id collisions)" if dropped else ""
    logger.info(f"PostgreSQL upsert complete: {len(seen_ids)} records in promo_items table{suffix}")
    return len(seen_ids)


def delete_retailer_promos_pg(
    retailer: str,
    validity_start: str = None,
    validity_end: str = None,
    page_number: Optional[int] = None,
    promo_folder_url: Optional[str] = None,
) -> int:
    """Delete promo items from PostgreSQL for a retailer.

    Optional scopes compose (all AND-ed together):
      - validity_start + validity_end: restrict to a single week's validity window
      - page_number: restrict to a single page of the folder (for --page N re-runs)
      - promo_folder_url: restrict to a single folder URL
    """
    import psycopg2

    clauses = ["source_retailer = %s"]
    params: list = [retailer]
    if validity_start and validity_end:
        clauses.append("validity_start = %s AND validity_end = %s")
        params.extend([validity_start, validity_end])
    if page_number is not None:
        clauses.append("page_number = %s")
        params.append(page_number)
    if promo_folder_url:
        clauses.append("promo_folder_url = %s")
        params.append(promo_folder_url)

    sql = f"DELETE FROM promo_items WHERE {' AND '.join(clauses)}"

    conn = psycopg2.connect(_get_pg_connection_string())
    try:
        cur = conn.cursor()
        cur.execute(sql, tuple(params))
        deleted = cur.rowcount
        conn.commit()
        cur.close()
    finally:
        conn.close()

    if deleted:
        logger.info(f"Deleted {deleted} existing records for {retailer}")
    return deleted


def delete_expired_promos_pg(today) -> int:
    """Delete promo_items rows whose validity_end is strictly before `today`.

    Called at the start of each ingest run so expired rows don't pile up.
    Safe to call repeatedly — expired rows are already hidden from the API
    by query-time filters, this is pure hygiene.
    """
    import psycopg2

    conn = psycopg2.connect(_get_pg_connection_string())
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM promo_items WHERE validity_end < %s", (today,))
        deleted = cur.rowcount
        conn.commit()
        cur.close()
    finally:
        conn.close()

    if deleted:
        logger.info(f"Deleted {deleted} expired promo_items (validity_end < {today})")
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
    validity_start: Optional[str] = None,
    validity_end: Optional[str] = None,
    page_filter: Optional[int] = None,
) -> list[PromoItem]:
    """Run the full ingestion pipeline for a store.

    Args:
        store_id: Canonical store name from stores.py (e.g. "colruyt")
        pdf_data: Raw PDF bytes (downloaded from R2)
        promo_folder_url: Optional URL of the promo folder source
        dry_run: If True, extract and parse only — no database upsert
        pdf_label: Human-readable label for logging (e.g. "colruyt/2026-W12/food.pdf")
        validity_start: If provided, unconditionally overrides Gemini's inferred
            folder validity_start so every item carries the folder's authoritative
            date (sourced from the folder metadata, not the PDF contents).
        validity_end: Same as validity_start, for the end date.
        page_filter: When set, only extract/upsert items for this 1-indexed page.

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
    if page_filter is not None:
        logger.info(f"Page filter: only page {page_filter}")

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set in environment")

    # Step 1: Extract from PDF via Gemini
    raw_data = extract_promos_from_pdf(pdf_data, config, page_filter=page_filter)

    # Folder metadata validity is authoritative — override Gemini's inference so
    # every item in this folder carries the exact same validity window as the
    # parent folder's R2 metadata.
    if validity_start:
        raw_data["validity_start"] = validity_start
    if validity_end:
        raw_data["validity_end"] = validity_end

    # Step 2: Parse and validate
    items = parse_promo_items(raw_data, canonical_store_id, promo_folder_url)

    if not items:
        logger.warning("No items extracted. Exiting.")
        return []

    # Step 2.3: Apply manual bbox overrides. Persists corrections across every re-ingest —
    # the 100% accuracy guarantee for known-bad pages. Runs before cropping so item
    # images are generated against the corrected bboxes.
    apply_bbox_overrides(items, promo_folder_url)

    # Step 2.5: Crop item images, enhance via Replicate FLUX, and upload to R2
    page_images = _render_pdf_pages(pdf_data)
    r2 = R2PromoStorage()
    crop_and_upload_item_images(items, page_images, r2, canonical_store_id)

    # Step 3: Summary + anomaly report
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

    # Bbox QA report — flags items that look suspicious so we can spot-check
    # without eyeballing every page. Runs even on dry-run.
    from promo_folders_pipelines.qa_report import detect_anomalies, format_report
    anomalies = detect_anomalies(items)
    folder_label = pdf_label or f"{canonical_store_id} folder"
    logger.info("\n" + format_report(anomalies, folder_label, len(items)))

    # Step 4: Upsert or dry-run
    if dry_run:
        logger.info("DRY RUN — skipping upsert")
    else:
        pg_count = upsert_to_postgres(items)
        logger.info(f"Done! {pg_count} promo records in promo_items table")

    return items

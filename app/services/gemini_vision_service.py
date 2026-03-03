"""
Gemini Vision service for receipt OCR and semantic line item extraction.

Replaces Veryfi for OCR extraction and handles:
- Line item extraction with normalized names
- Belgian pricing conventions (comma→dot, Hoeveelheidsvoordeel)
- Deposit item detection (Leeggoed/Vidange)
- Granular categorization (~200 categories)
"""

import asyncio
import io
import json
import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Optional

from google import genai
from pydantic import BaseModel as PydanticBaseModel, Field
from google.genai import types

from app.core.exceptions import GeminiAPIError
from app.config import get_settings
from app.core.categories import CATEGORIES_PROMPT_LIST, GRANULAR_CATEGORIES, get_parent_category
from app.core.stores import STORES_PROMPT_LIST

settings = get_settings()
logger = logging.getLogger(__name__)

# Per-user semaphore: limits each user to 2 concurrent Gemini generate_content calls.
# Without this, concurrent uploads from the same user hit the API simultaneously and
# get queued server-side, escalating latency from ~60s to 180s+ for later requests.
_user_semaphores: dict[str, asyncio.Semaphore] = {}

# Singleton genai.Client — reuses the underlying httpx.AsyncClient connection pool across
# all background tasks. Creating a new client per task means a new TLS handshake and new
# connection pool for every receipt. The singleton is safe for concurrent asyncio use.
_gemini_client: genai.Client | None = None


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _gemini_client


def _get_user_semaphore(user_id: str) -> asyncio.Semaphore:
    if user_id not in _user_semaphores:
        _user_semaphores[user_id] = asyncio.Semaphore(2)
    return _user_semaphores[user_id]


@dataclass
class ExtractedLineItem:
    """Represents a line item extracted and normalized by Gemini Vision."""

    item_name: str  # Product description text from receipt (original casing, no codes/prices)
    normalized_name: str  # Cleaned, semantic name (always lowercase)
    normalized_brand: Optional[str]  # Brand name only (lowercase, for semantic search)
    is_premium: bool  # True if premium/expensive brand, False if store/house brand
    quantity: int
    unit_price: Optional[float]
    total_price: float  # Can be negative for discount lines
    is_discount: bool  # True for discount/bonus lines (negative amounts)
    is_deposit: bool
    granular_category: str  # Detailed category
    parent_category: str  # Broad category
    unit_of_measure: Optional[str]  # kg/g/l/ml/piece
    weight_or_volume: Optional[float]  # actual weight/volume
    price_per_unit_measure: Optional[float]  # price per kg/liter
    # Data Platform fields (dp_) — for EAN matching & Pinecone vector search
    dp_expanded_description: Optional[str]  # Full product text for vector search embedding
    dp_pack_quantity: Optional[int]  # Multi-pack count (6 from "6x33cl"), 1 for singles
    dp_pack_size: Optional[float]  # TOTAL pack size in ml or g (matches Daltix pack_size)
    dp_pack_unit: Optional[str]  # "ml" or "g" (matches Daltix pack_unit)
    dp_product_variant: Optional[str]  # flavor/style/sub-type (zero, bruin, paprika)
    dp_article_code: Optional[str]  # Article/PLU/barcode code from receipt
    dp_is_bio: bool  # True if organic (bio/biologisch/biologique)

    @property
    def lookup_key(self) -> str:
        """Deterministic composite key for receipt-item → SKU mapping."""
        pack_qty = self.dp_pack_quantity or 1
        pack_size = self.dp_pack_size if self.dp_pack_size is not None else ""
        pack_unit = self.dp_pack_unit or ""
        return f"{self.normalized_name}|{pack_qty}|{pack_size}|{pack_unit}"


@dataclass
class GeminiExtractionResult:
    """Complete extraction result from Gemini Vision."""

    vendor_name: str
    receipt_date: Optional[date]
    total: Optional[float]
    line_items: list[ExtractedLineItem]
    receipt_time: Optional[str]  # HH:MM format
    payment_method: Optional[str]  # bancontact/visa/mastercard/cash/payconiq/meal_vouchers/mixed
    total_savings: Optional[float]  # total discount amount (positive number)
    store_branch: Optional[str]  # store location/branch


# Pydantic schemas passed as response_schema to Gemini — structurally constrains the JSON output
# so the model cannot return a bare array instead of the expected object.
class _LineItemSchema(PydanticBaseModel):
    item_name: str = Field(
        description="Product description text from the receipt line in original casing. Include brand, product name, variant, and size/packaging info. Exclude article codes, PLU numbers, quantity counts, and prices."
    )
    normalized_name: str = Field(
        description="Clean, full product name in lowercase. Keep brand name. Remove quantities (450ml, 1L, 500g), packaging types (PET, Blik, Fles), and receipt codes. Maintain original language (Dutch/French)"
    )
    normalized_brand: Optional[str] = Field(
        default=None,
        description="Brand/manufacturer name only, lowercase. For store/house brands (Boni, 365, Everyday, Cara), use the house brand name. For fresh/ready-made items (traiteur, deli, bakery, prepared meals) without a visible brand, use 'in-house'. null only for truly generic items (loose fruit, vegetables by weight)"
    )
    is_premium: bool = Field(
        description="true for premium/name brands (Coca-Cola, Jupiler, Danone, Lay's), false for store/house brands (Boni, 365, Everyday, Cara) and unbranded items"
    )
    quantity: int = Field(
        description="Number of items — parse from '2x', 'x3', '2 ST', etc. Default 1"
    )
    unit_price: Optional[float] = Field(
        default=None,
        description="Price per single item if shown separately on receipt"
    )
    total_price: float = Field(
        description="Total line price. Convert Belgian comma decimals to dots (2,99 → 2.99). Use NEGATIVE values for discount/bonus lines"
    )
    is_discount: bool = Field(
        description="true for discount/bonus lines: Hoeveelheidsvoordeel, Korting, Bon korting, Promotie, Actie, Reductie — any line that reduces the total"
    )
    is_deposit: bool = Field(
        description="true ONLY for bottle/can deposit items: Leeggoed, Vidange, Statiegeld"
    )
    granular_category: str = Field(
        description="One category from the provided category list"
    )
    unit_of_measure: Optional[str] = Field(
        default=None,
        description="Unit for weighed/measured items: kg, g, l, ml, or piece. null for standard packaged items"
    )
    weight_or_volume: Optional[float] = Field(
        default=None,
        description="Actual weight or volume purchased (numeric only). Parse from '0.547 kg', '1.5 l'. null if not shown"
    )
    price_per_unit_measure: Optional[float] = Field(
        default=None,
        description="Per-unit price (per kg, per liter). Parse from '5.99/kg', '1.29/l'. null if not shown"
    )
    dp_expanded_description: Optional[str] = Field(
        default=None,
        description="Full product text in lowercase, original language. Include brand, name, variant, pack info, packaging type — keep ALL product-identifying info"
    )
    dp_pack_quantity: Optional[int] = Field(
        default=None,
        description="Multi-pack count: '6X33CL'→6, '4x125g'→4. Default 1 for singles"
    )
    dp_pack_size: Optional[float] = Field(
        default=None,
        description="TOTAL pack size in ml (liquids) or g (solids). Multi-packs: multiply qty×per-item. '6X33CL'→1980.0, '1,5L'→1500.0"
    )
    dp_pack_unit: Optional[str] = Field(
        default=None,
        description="'ml' for liquids, 'g' for solids. null if no size info"
    )
    dp_product_variant: Optional[str] = Field(
        default=None,
        description="Flavor/style/sub-type in lowercase: 'zero', 'bruin', 'paprika', 'pils'. null if base product"
    )
    dp_article_code: Optional[str] = Field(
        default=None,
        description="Article/PLU/barcode from receipt ('ART 123456', 'PLU 4011'). null if not visible"
    )
    dp_is_bio: bool = Field(
        description="true if BIO/BIOLOGISCH/BIOLOGIQUE/ORGANIC in text, false otherwise"
    )


class _ReceiptSchema(PydanticBaseModel):
    vendor_name: str = Field(
        description="Store/retailer name — must be one of the exact store names from the provided list, or 'Other'"
    )
    receipt_date: Optional[str] = Field(
        default=None,
        description="Receipt date in YYYY-MM-DD format. Convert DD/MM/YYYY to YYYY-MM-DD"
    )
    receipt_time: Optional[str] = Field(
        default=None,
        description="Time of purchase in HH:MM 24-hour format. null if not found"
    )
    payment_method: Optional[str] = Field(
        default=None,
        description="One of: bancontact, visa, mastercard, cash, payconiq, meal_vouchers, mixed. null if not found"
    )
    total_savings: Optional[float] = Field(
        default=None,
        description="Total discount amount as a POSITIVE number (absolute sum of all discount lines). null if no discounts"
    )
    store_branch: Optional[str] = Field(
        default=None,
        description="Store location/branch (city or street), NOT the chain name. e.g., 'Colruyt Leuven' → 'Leuven'"
    )
    total: Optional[float] = Field(
        default=None,
        description="Receipt total amount"
    )
    line_items: list[_LineItemSchema] = Field(
        description="All extracted line items. Include discount lines with negative total_price. Skip subtotals and payment lines"
    )


class GeminiVisionService:
    """Gemini Vision integration for receipt OCR and extraction."""

    MODEL = "gemini-3.1-pro-preview"
    MAX_TOKENS = 32000  # Actual output ~6k tokens + capped thinking budget; pro model supports 64k output

    SYSTEM_PROMPT = '''You are a Belgian grocery receipt analyzer. Extract and normalize line items from receipt images.

## EXTRACTION RULES

### Vendor Name
- Identify the store/retailer from the receipt
- You MUST use one of these exact store names: {stores}
- If the store is not in the list above, use "Other"

### Receipt Date
- Extract the date from the receipt in YYYY-MM-DD format
- Look for "Datum:", "Date:", or date patterns like "02/02/2026" or "02-02-2026"
- Convert DD/MM/YYYY to YYYY-MM-DD

### Receipt Time
- Extract the time of purchase in HH:MM format (24-hour)
- Look for "Tijd:", "Heure:", time near the date, or patterns like "14:32"
- Return null if no time is found

### Payment Method
- Identify the payment method and normalize to one of: bancontact, visa, mastercard, cash, payconiq, meal_vouchers, mixed
- Look for "Bancontact", "VISA", "Mastercard", "Cash", "Payconiq", "Edenred", "Sodexo", "Monizze"
- For Edenred/Sodexo/Monizze, use "meal_vouchers"
- If multiple payment methods are used, use "mixed"
- Return null if no payment method is found

### Total Savings
- Calculate the total discount amount as a POSITIVE number
- Sum up all discount lines (lines where is_discount=true) and return the absolute value
- Return null if there are no discounts

### Store Branch
- Extract the store location/branch (the city, street, or branch identifier)
- This is the location part of the store name, NOT the store chain name
- Examples: "Colruyt Leuven" → "Leuven", "Delhaize Etterbeek" → "Etterbeek"
- Return null if no branch/location is found

### Line Items - Extract these fields:

1. **item_name**: Product description text from the receipt line, in original casing (NOT lowercase).
   - KEEP: brand name, product name, variant/flavor, size/weight info (500g, 1L, 6X33CL), packaging type (PET, Blik)
   - REMOVE: article codes (A 14515), PLU numbers, quantity counts (the "1" or "2x" at the end), unit prices and total prices
   - Preserve the original casing and language from the receipt
   - Examples:
     - "A 14515 BONI BIO volkorenspaghetti 500g 1 0,99 0,99" → "BONI BIO volkorenspaghetti 500g"
     - "JUPILER PILS 6X33CL PET" → "JUPILER PILS 6X33CL PET"
     - "123456 COCA COLA ZERO 1,5L PET 2 3,58" → "COCA COLA ZERO 1,5L PET"
     - "LAY'S CHIPS PAPRIKA 250G" → "LAY'S CHIPS PAPRIKA 250G"
     - "BANANEN 1KG" → "BANANEN 1KG"

2. **normalized_name**: Clean, full product name used for product matching. This is the primary field for matching receipt items to product databases (EAN lookup).
   - ALWAYS output in **lowercase**
   - ALWAYS KEEP the brand/manufacturer name — it is part of the product identity
   - REMOVE quantities (450ml, 1L, 500g, 10st, 6x33cl, etc.)
   - REMOVE packaging types (PET, Blik, Fles, Doos, Brik, etc.)
   - REMOVE receipt codes, article numbers, and barcodes
   - Keep the product's natural word order as on the receipt (after removing quantities/packaging)
   - Maintain original language (Dutch/French)
   - **CRITICAL**: The SAME product must ALWAYS produce the SAME normalized_name, regardless of receipt format or OCR variations
   - Examples:
     - "JUPILER PILS 6X33CL PET" → "jupiler pils"
     - "BONI VOLLE MELK 1L" → "boni volle melk"
     - "COCA COLA ZERO 1,5L PET" → "coca-cola zero"
     - "VANDEMOORTELE VINAIGRETTE CAESAR 450ML" → "vandemoortele vinaigrette caesar"
     - "LEFFE BRUIN 6X33CL" → "leffe bruin"
     - "DR. OETKER CASA DI MAMA SALAME 390G" → "dr. oetker casa di mama salame"
     - "LAY'S CHIPS PAPRIKA 250G" → "lay's chips paprika"
     - "DEVOS LEMMENS MAYONAISE 300ML" → "devos lemmens mayonaise"
     - "DUYVIS BORRELNOOTJES HOT 275G" → "duyvis borrelnootjes hot"
     - "BANANEN 1KG" → "bananen"
     - "CARA PILS 6X33CL" → "cara pils"
     - "365 PILS 6X33CL" → "365 pils"
     - "ABSOLUT VODKA 35CL" → "absolut vodka"

3. **normalized_brand**: The brand/manufacturer name ONLY, in **lowercase**. Used as a pre-filter for product matching.
   - Extract the product's brand/manufacturer, NOT the store name
   - For store/house brands (Boni, 365, Everyday, Cara, Delhaize brand), use the house brand name
   - If a fresh/ready-made food item (traiteur, deli, bakery, prepared meals) has no visible brand, default to "in-house"
   - Only use null for truly generic unbranded items (loose fruit, vegetables by weight)
   - Examples:
     - "JUPILER PILS 6X33CL PET" → "jupiler"
     - "BONI VOLLE MELK 1L" → "boni"
     - "COCA COLA ZERO 1,5L PET" → "coca-cola"
     - "VANDEMOORTELE VINAIGRETTE CAESAR 450ML" → "vandemoortele"
     - "LEFFE BRUIN 6X33CL" → "leffe"
     - "LAY'S CHIPS PAPRIKA 250G" → "lay's"
     - "CARA PILS 6X33CL" → "cara"
     - "365 PILS 6X33CL" → "365"
     - "ABSOLUT VODKA 35CL" → "absolut"
     - "KIP KYOTO MET RIJST" → "in-house"
     - "BAMI OMELET KIP GROENTEN" → "in-house"
     - "BANANEN 1KG" → null

4. **is_premium**: Boolean flag for brand tier classification:
   - `true` = Premium/name brand (well-known, nationally/internationally advertised brands)
     - Examples: Coca-Cola, Jupiler, Leffe, Danone, Lay's, Nutella, Vandemoortele, Devos Lemmens
   - `false` = Store/house brand or budget brand (private label, supermarket own brand)
     - Examples: Boni (Colruyt), 365 (Delhaize), Everyday (Colruyt), Cara (Lidl house brand for beer), Nixe (Lidl)
   - `false` also for unbranded/generic items (loose fruit, vegetables, bakery items without brand)

5. **quantity**: Number of items (parse from "2x", "x3", "2 ST", etc.). Default to 1.

6. **unit_price**: Price per single item (if shown separately on receipt)

7. **total_price**: Total line price
   - Convert Belgian comma decimals to dots: "2,99" → 2.99
   - For discount/bonus lines, use NEGATIVE values (e.g., -1.50 for a 1.50€ discount)
   - Handle "Actieprijs" (promotional price): use that price for the item

8. **is_discount**: True for discount/bonus line items:
   - "Hoeveelheidsvoordeel" (quantity discount)
   - "Korting", "Bon korting", "Promotie"
   - "Actie", "Reductie"
   - Any line that reduces the total (negative amount)
   - These lines should have NEGATIVE total_price values
   - The normalized_name should describe the discount (e.g., "korting hoeveelheidsvoordeel")

9. **is_deposit**: True ONLY for deposit items:
   - "Leeggoed" (Dutch)
   - "Vidange" (French)
   - "Statiegeld"
   - These are bottle/can deposits, NOT the actual products

10. **unit_of_measure**: The unit shown on the receipt for weighed/measured items:
    - Use: "kg", "g", "l", "ml", or "piece"
    - Look for per-kg/per-liter pricing lines (e.g., "1.234 kg x 5.99/kg")
    - Return null for standard packaged items without weight/volume info

11. **weight_or_volume**: The actual weight or volume purchased:
    - Parse from lines like "0.547 kg", "1.5 l", "250 g"
    - Return the numeric value only (use unit_of_measure for the unit)
    - Return null if not shown on receipt

12. **price_per_unit_measure**: The per-unit price (price per kg, per liter, etc.):
    - Parse from lines like "5.99/kg", "1.29/l"
    - Return null if not shown on receipt

### Data Platform Fields (dp_ prefix) — for EAN matching

13. **dp_expanded_description**: Full product text (lowercase, original language). Include brand, name, variant, pack info, packaging type. Keep ALL product-identifying info unlike normalized_name.

14. **dp_pack_quantity**: Multi-pack count. "6X33CL"→6, "4x125g"→4. Default 1 for singles.

15. **dp_pack_size**: TOTAL pack size in ml (liquids) or g (solids). Multi-packs: multiply qty×per-item. "6X33CL"→1980.0, "1,5L"→1500.0, "250G"→250.0. null if unknown.

16. **dp_pack_unit**: "ml" for liquids, "g" for solids. null if no size info.

17. **dp_product_variant**: Flavor/style/sub-type (lowercase). "zero","bruin","paprika","pils". null if base product.

18. **dp_article_code**: Article/PLU/barcode from receipt ("ART 123456", "PLU 4011"). null if not visible.

19. **dp_is_bio**: true if BIO/BIOLOGISCH/BIOLOGIQUE/ORGANIC in text, false otherwise.

### IMPORTANT RULES
- INCLUDE discount/bonus lines with NEGATIVE total_price values (these reduce the receipt total)
- Skip subtotals, totals, payment lines
- Each product should appear ONCE even if the receipt shows quantity
- For multi-section receipts with overlapping items, deduplicate by product name

### Granular Categories
Assign ONE category from this list for each item:
{categories}

## OUTPUT FORMAT
Return a JSON object with this structure:
- "vendor_name": string (MUST be one of the store names listed above)
- "receipt_date": "YYYY-MM-DD"
- "receipt_time": "HH:MM" or null
- "payment_method": string or null (bancontact/visa/mastercard/cash/payconiq/meal_vouchers/mixed)
- "total_savings": number or null (positive, sum of all discount amounts)
- "store_branch": string or null (location/branch name)
- "total": number (receipt total)
- "line_items": array of objects, each with:
  - "item_name": string (raw receipt text, unmodified)
  - "normalized_name": string (cleaned name, lowercase)
  - "normalized_brand": string or null
  - "is_premium": boolean
  - "quantity": integer
  - "unit_price": number or null
  - "total_price": number (negative for discounts)
  - "is_discount": boolean
  - "is_deposit": boolean
  - "granular_category": string (from list above)
  - "unit_of_measure": string or null (kg/g/l/ml/piece)
  - "weight_or_volume": number or null
  - "price_per_unit_measure": number or null
  - "dp_expanded_description": string or null (full product text for vector search)
  - "dp_pack_quantity": integer or null (multi-pack count, 1 for singles)
  - "dp_pack_size": number or null (total pack size in ml or g)
  - "dp_pack_unit": string or null ("ml" or "g")
  - "dp_product_variant": string or null (flavor/style/sub-type)
  - "dp_article_code": string or null (article/PLU code from receipt)
  - "dp_is_bio": boolean (true if organic)

Extract all line items from this receipt.'''

    def __init__(self):
        self.client = _get_gemini_client()

    async def extract_receipt(self, file_content: bytes, user_id: str) -> GeminiExtractionResult:
        """Extract and normalize receipt data using Gemini Vision.

        Uploads PDF via Files API, runs extraction, then cleans up.
        A per-user semaphore limits concurrent generate_content calls to prevent
        API-side queuing that compounds latency under concurrent uploads.
        """
        system_prompt = (
            self.SYSTEM_PROMPT
            .replace("{categories}", CATEGORIES_PROMPT_LIST)
            .replace("{stores}", STORES_PROMPT_LIST)
        )

        logger.info(
            f"Gemini extraction starting: content_size={len(file_content)} bytes, "
            f"model={self.MODEL}, max_tokens={self.MAX_TOKENS}, user_id={user_id}"
        )

        # Verify API key is set
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            logger.error("GEMINI_API_KEY is not set!")
            raise GeminiAPIError("GEMINI_API_KEY not configured", details={"error_type": "config"})
        logger.info(f"API key present: {api_key[:8]}...{api_key[-4:]} (length={len(api_key)})")

        # Upload PDF to Gemini Files API
        t0 = time.monotonic()
        try:
            uploaded_file = await self.client.aio.files.upload(
                file=io.BytesIO(file_content),
                config=types.UploadFileConfig(
                    mime_type="application/pdf",
                    display_name="receipt.pdf",
                ),
            )
            upload_elapsed = time.monotonic() - t0
            logger.info(
                f"⏱ gemini_file_upload: {upload_elapsed:.3f}s — "
                f"file_name={uploaded_file.name}, "
                f"state={getattr(uploaded_file, 'state', 'unknown')}, "
                f"uri={getattr(uploaded_file, 'uri', 'N/A')}"
            )
        except Exception as e:
            logger.error(f"Gemini file upload failed after {time.monotonic() - t0:.3f}s: {type(e).__name__}: {e}")
            raise GeminiAPIError(
                f"File upload failed: {e}",
                details={"error_type": "upload_failed", "error": str(e)},
            )

        response_text = None
        try:
            logger.info(
                f"Calling generate_content: model={self.MODEL}, "
                f"file={uploaded_file.name}, timeout=900s, AFC=disabled"
            )
            t0 = time.monotonic()
            async with _get_user_semaphore(user_id):
                semaphore_wait = time.monotonic() - t0
                if semaphore_wait > 0.1:
                    logger.info(f"⏱ semaphore_wait: {semaphore_wait:.3f}s (another request was in progress)")
                t1 = time.monotonic()
                response = await asyncio.wait_for(
                    self.client.aio.models.generate_content(
                        model=self.MODEL,
                        contents=[uploaded_file],
                        config=types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            max_output_tokens=self.MAX_TOKENS,
                            temperature=1.0,
                            response_mime_type="application/json",
                            response_schema=_ReceiptSchema,
                            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
                        ),
                    ),
                    timeout=900,  # 15 minutes — thinking models can be slow
                )
            generate_elapsed = time.monotonic() - t1
            total_elapsed = time.monotonic() - t0
            logger.info(f"⏱ gemini_generate_content: {generate_elapsed:.3f}s (total incl. semaphore: {total_elapsed:.3f}s)")

            # Log full response metadata
            logger.info(
                f"Response metadata: "
                f"candidates={len(response.candidates) if response.candidates else 0}, "
                f"finish_reason={response.candidates[0].finish_reason if response.candidates else 'N/A'}, "
                f"has_text={bool(response.text) if hasattr(response, 'text') else 'N/A'}"
            )

            # Log token usage
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                um = response.usage_metadata
                logger.info(
                    f"Gemini token usage: "
                    f"input={getattr(um, 'prompt_token_count', '?')}, "
                    f"output={getattr(um, 'candidates_token_count', '?')}, "
                    f"total={getattr(um, 'total_token_count', '?')}"
                )
            else:
                logger.warning("No usage_metadata in response")

            # Check for truncation
            if response.candidates and response.candidates[0].finish_reason:
                finish_reason = str(response.candidates[0].finish_reason)
                if "MAX_TOKENS" in finish_reason or "LENGTH" in finish_reason:
                    logger.warning(
                        f"Gemini response truncated (finish_reason={finish_reason}). "
                        f"Receipt may have too many items for current token limit."
                    )

            response_text = response.text
            if not response_text:
                # Log everything we can about the response for debugging
                logger.error(
                    f"Gemini returned empty response. "
                    f"Candidates: {response.candidates}, "
                    f"prompt_feedback: {getattr(response, 'prompt_feedback', 'N/A')}"
                )
                raise GeminiAPIError(
                    "Gemini returned empty response",
                    details={"error_type": "empty_response"},
                )

            logger.info(f"Response text length: {len(response_text)} chars")
            data = json.loads(response_text)
            logger.info(
                f"Gemini response parsed: vendor={data.get('vendor_name')}, "
                f"items={len(data.get('line_items', []))}, "
                f"date={data.get('receipt_date')}, total={data.get('total')}"
            )

            return self._build_result(data)

        except asyncio.TimeoutError:
            elapsed = time.monotonic() - t0
            logger.error(f"Gemini generate_content timed out after {elapsed:.1f}s (limit=900s)")
            raise GeminiAPIError(
                "Receipt extraction timed out",
                details={"error_type": "timeout", "elapsed_seconds": elapsed},
            )
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response as JSON: {e}")
            logger.error(f"Raw response (first 1000 chars): {response_text[:1000] if response_text else 'empty'}")
            raise GeminiAPIError(
                "Failed to parse extraction response",
                details={"error_type": "parse_error", "parse_error": str(e)},
            )
        except GeminiAPIError:
            raise
        except Exception as e:
            elapsed = time.monotonic() - t0
            logger.exception(f"Extraction failed after {elapsed:.1f}s: {type(e).__name__}: {e}")
            raise GeminiAPIError(
                f"Extraction failed: {str(e)}",
                details={"error_type": "unexpected", "error_class": type(e).__name__, "error": str(e)},
            )
        finally:
            # Best-effort cleanup — files auto-expire after 48h anyway
            try:
                await self.client.aio.files.delete(name=uploaded_file.name)
                logger.info(f"Cleaned up uploaded file: {uploaded_file.name}")
            except Exception as cleanup_err:
                logger.warning(f"File cleanup failed (non-critical): {cleanup_err}")

    def _build_result(self, data: dict) -> GeminiExtractionResult:
        """Build extraction result from parsed JSON."""
        # Parse date
        receipt_date = None
        if data.get("receipt_date"):
            try:
                receipt_date = date.fromisoformat(data["receipt_date"])
            except ValueError:
                logger.warning(f"Could not parse date: {data.get('receipt_date')}")

        # Build line items
        line_items = []
        for item in data.get("line_items", []):
            granular = item.get("granular_category", "Other")
            # Validate granular category, fallback to "Other"
            if granular not in GRANULAR_CATEGORIES:
                logger.warning(f"Unknown granular category: {granular}, using 'Other'")
                granular = "Other"
            parent = get_parent_category(granular)

            # Parse prices
            total_price = item.get("total_price")
            if total_price is None:
                continue  # Skip items without price

            try:
                total_price = float(total_price)
            except (ValueError, TypeError):
                logger.warning(f"Invalid total_price: {total_price}, skipping item")
                continue

            unit_price = item.get("unit_price")
            if unit_price is not None:
                try:
                    unit_price = float(unit_price)
                except (ValueError, TypeError):
                    unit_price = None

            # Ensure normalized_name is always lowercase
            normalized_name = item.get("normalized_name", "")
            if normalized_name:
                normalized_name = normalized_name.lower()

            # Extract and lowercase normalized_brand
            normalized_brand = item.get("normalized_brand")
            if normalized_brand:
                normalized_brand = normalized_brand.lower()

            # Parse unit measure fields
            unit_of_measure = item.get("unit_of_measure")
            if unit_of_measure and unit_of_measure not in ("kg", "g", "l", "ml", "piece"):
                unit_of_measure = None

            weight_or_volume = item.get("weight_or_volume")
            if weight_or_volume is not None:
                try:
                    weight_or_volume = float(weight_or_volume)
                except (ValueError, TypeError):
                    weight_or_volume = None

            price_per_unit_measure = item.get("price_per_unit_measure")
            if price_per_unit_measure is not None:
                try:
                    price_per_unit_measure = float(price_per_unit_measure)
                except (ValueError, TypeError):
                    price_per_unit_measure = None

            # Parse dp_ fields
            dp_expanded_description = item.get("dp_expanded_description")
            if dp_expanded_description:
                dp_expanded_description = dp_expanded_description.lower().strip()

            dp_pack_quantity = item.get("dp_pack_quantity")
            if dp_pack_quantity is not None:
                try:
                    dp_pack_quantity = int(dp_pack_quantity)
                except (ValueError, TypeError):
                    dp_pack_quantity = None

            dp_pack_size = item.get("dp_pack_size")
            if dp_pack_size is not None:
                try:
                    dp_pack_size = float(dp_pack_size)
                except (ValueError, TypeError):
                    dp_pack_size = None

            dp_pack_unit = item.get("dp_pack_unit")
            if dp_pack_unit and dp_pack_unit.lower() not in ("ml", "g"):
                dp_pack_unit = None
            elif dp_pack_unit:
                dp_pack_unit = dp_pack_unit.lower()

            dp_product_variant = item.get("dp_product_variant")
            if dp_product_variant:
                dp_product_variant = dp_product_variant.lower().strip()
                if not dp_product_variant:
                    dp_product_variant = None

            dp_article_code = item.get("dp_article_code")
            if dp_article_code:
                dp_article_code = dp_article_code.strip()
                if not dp_article_code:
                    dp_article_code = None

            line_items.append(
                ExtractedLineItem(
                    item_name=item.get("item_name", ""),
                    normalized_name=normalized_name,
                    normalized_brand=normalized_brand,
                    is_premium=bool(item.get("is_premium", False)),
                    quantity=int(item.get("quantity", 1)),
                    unit_price=unit_price,
                    total_price=total_price,
                    is_discount=bool(item.get("is_discount", False)),
                    is_deposit=bool(item.get("is_deposit", False)),
                    granular_category=granular,
                    parent_category=parent,
                    unit_of_measure=unit_of_measure,
                    weight_or_volume=weight_or_volume,
                    price_per_unit_measure=price_per_unit_measure,
                    dp_expanded_description=dp_expanded_description,
                    dp_pack_quantity=dp_pack_quantity,
                    dp_pack_size=dp_pack_size,
                    dp_pack_unit=dp_pack_unit,
                    dp_product_variant=dp_product_variant,
                    dp_article_code=dp_article_code,
                    dp_is_bio=bool(item.get("dp_is_bio", False)),
                )
            )

        # Parse receipt-level insights
        receipt_time = data.get("receipt_time")
        if receipt_time:
            # Validate HH:MM format
            try:
                parts = receipt_time.split(":")
                int(parts[0])
                int(parts[1])
            except (ValueError, IndexError):
                receipt_time = None

        payment_method = data.get("payment_method")
        valid_methods = {"bancontact", "visa", "mastercard", "cash", "payconiq", "meal_vouchers", "mixed"}
        if payment_method and payment_method.lower() not in valid_methods:
            payment_method = None
        elif payment_method:
            payment_method = payment_method.lower()

        total_savings = data.get("total_savings")
        if total_savings is not None:
            try:
                total_savings = abs(float(total_savings))
                if total_savings == 0:
                    total_savings = None
            except (ValueError, TypeError):
                total_savings = None

        store_branch = data.get("store_branch")
        if store_branch:
            store_branch = store_branch.strip()
            if not store_branch:
                store_branch = None

        return GeminiExtractionResult(
            vendor_name=data.get("vendor_name", "Unknown"),
            receipt_date=receipt_date,
            total=data.get("total"),
            line_items=line_items,
            receipt_time=receipt_time,
            payment_method=payment_method,
            total_savings=total_savings,
            store_branch=store_branch,
        )


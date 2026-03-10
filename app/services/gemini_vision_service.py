"""
Gemini Vision service for receipt OCR and semantic line item extraction.

 OCR extraction and handles:
- Line item extraction with normalized names
- Belgian pricing conventions (comma→dot, Hoeveelheidsvoordeel)
- Deposit item detection (Leeggoed/Vidange)
- Granular categorization (~200 categories)
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Optional

from google import genai
from pydantic import BaseModel as PydanticBaseModel, Field
from google.genai import types

from google.genai import errors as genai_errors

from app.core.exceptions import GeminiAPIError
from app.config import get_settings
from app.core.categories import CATEGORIES_PROMPT_LIST, GRANULAR_CATEGORIES, get_parent_category
from app.core.stores import STORES_PROMPT_LIST

settings = get_settings()
logger = logging.getLogger(__name__)

# Deterministic unit conversion: raw receipt unit → (target unit, multiplier)
# Liquids normalize to ml, solids normalize to g.
_UNIT_CONVERSIONS: dict[str, tuple[str, float]] = {
    "cl": ("ml", 10.0),
    "ml": ("ml", 1.0),
    "l":  ("ml", 1000.0),
    "g":  ("g", 1.0),
    "kg": ("g", 1000.0),
}

# Global semaphore: caps concurrent Gemini generate_content calls across all users.
# Paid Tier 1 = 150 RPM. At ~60s per call, 10 concurrent ≈ 10 RPM (well within limit).
_gemini_semaphore = asyncio.Semaphore(10)

# Singleton genai.Client — reuses the underlying httpx.AsyncClient connection pool across
# all background tasks. Creating a new client per task means a new TLS handshake and new
# connection pool for every receipt. The singleton is safe for concurrent asyncio use.
_gemini_client: genai.Client | None = None


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _gemini_client


@dataclass
class ExtractedLineItem:
    """Represents a line item extracted and normalized by Gemini Vision."""

    item_name: str  # Product description text from receipt (ALL CAPS, no codes/prices)
    normalized_name: str  # Cleaned, semantic name (always lowercase)
    normalized_brand: Optional[str]  # Brand name only (lowercase, for semantic search)
    is_premium: bool  # True if premium/expensive brand, False if store/house brand
    quantity: int
    unit_price: Optional[float]
    total_price: float  # Always positive
    is_discount: bool  # True for discount/bonus lines
    is_deposit: bool  # True for any deposit line (charge or refund)
    is_deposit_refund: bool  # True only for deposit refund lines (returning containers)
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
        variant = self.dp_product_variant or ""
        is_bio = "bio" if self.dp_is_bio else ""
        return f"{self.normalized_name}|{pack_qty}|{pack_size}|{pack_unit}|{variant}|{is_bio}"


@dataclass
class GeminiExtractionResult:
    """Complete extraction result from Gemini Vision."""

    vendor_name: str
    receipt_date: Optional[date]
    total: Optional[float]
    line_items: list[ExtractedLineItem]
    receipt_time: Optional[str]  # HH:MM format
    payment_method: Optional[str]  # bancontact/visa/mastercard/cash/payconiq/meal_vouchers/mixed
    store_branch: Optional[str]  # store location/branch


# Pydantic schemas passed as response_schema to Gemini — structurally constrains the JSON output
# so the model cannot return a bare array instead of the expected object.
class _LineItemSchema(PydanticBaseModel):
    item_name: str = Field(description="Product text from receipt in ALL CAPS, without codes or prices")
    normalized_name: str = Field(description="Lowercase canonical product name for matching")
    normalized_brand: Optional[str] = Field(default=None, description="Lowercase brand name, or null")
    is_premium: bool = Field(description="true for national/premium brands, false for house/store brands")
    quantity: int = Field(description="Item count, default 1")
    unit_price: Optional[float] = Field(default=None, description="Per-unit price if shown, else null")
    total_price: float = Field(description="Positive float, dot decimal")
    is_discount: bool = Field(description="true if this line is a price reduction")
    is_deposit: bool = Field(description="true for any container deposit line")
    is_deposit_refund: bool = Field(description="true only for deposit refund (returning containers)")
    granular_category: str = Field(description="Category from the provided list, or 'Other'")
    unit_of_measure: Optional[str] = Field(default=None, description="kg, g, l, ml, or piece — null for packaged items")
    weight_or_volume: Optional[float] = Field(default=None, description="Measured quantity as float, or null")
    price_per_unit_measure: Optional[float] = Field(default=None, description="Per-kg or per-liter price as float, or null")
    dp_expanded_description: Optional[str] = Field(default=None, description="Full product text in lowercase for search, or null")
    dp_pack_quantity: Optional[int] = Field(default=None, description="Multi-pack count, 1 for singles")
    dp_per_item_size: Optional[float] = Field(default=None, description="Size of ONE item as printed on receipt. '6X33CL'→33, '1,5L'→1.5, '500g'→500. Do NOT multiply by pack quantity")
    dp_pack_unit: Optional[str] = Field(default=None, description="Unit as printed on receipt, lowercase: 'cl', 'ml', 'l', 'g', 'kg'. Do NOT convert units")
    dp_product_variant: Optional[str] = Field(default=None, description="Flavor/sub-type in lowercase, or null")
    dp_article_code: Optional[str] = Field(default=None, description="Article/PLU/barcode from receipt, or null")
    dp_is_bio: bool = Field(description="true if organic/bio product")


class _ReceiptSchema(PydanticBaseModel):
    vendor_name: str = Field(description="Store name from the provided list, or 'Other'")
    receipt_date: Optional[str] = Field(default=None, description="YYYY-MM-DD format")
    receipt_time: Optional[str] = Field(default=None, description="HH:MM 24-hour format, or null")
    payment_method: Optional[str] = Field(default=None, description="bancontact/visa/mastercard/cash/payconiq/meal_vouchers/mixed, or null")
    store_branch: Optional[str] = Field(default=None, description="Store location/branch only, or null")
    total: Optional[float] = Field(default=None, description="Net amount paid")
    line_items: list[_LineItemSchema] = Field(description="All line items including discounts and deposits")


class GeminiVisionService:
    """Gemini Vision integration for receipt OCR and extraction."""

    MODEL = "gemini-3.1-flash-lite-preview"
    MAX_TOKENS = 32000
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB — phone-scanned receipt PDFs are typically 100KB–2MB

    SYSTEM_PROMPT = '''You are a Belgian grocery receipt analyzer. Extract and normalize line items from receipt images.

## RECEIPT-LEVEL FIELDS

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

### Store Branch
- Extract the store location/branch (the city, street, or branch identifier)
- This is the location part of the store name, NOT the store chain name
- Examples: "Colruyt Leuven" → "Leuven", "Delhaize Etterbeek" → "Etterbeek"
- Return null if no branch/location is found

## ITEM EXTRACTION RULES

- INCLUDE all line types: regular products, discount lines, and deposit lines
- Skip subtotals, totals, payment lines, VAT summary lines, loyalty point summaries
- One line item per receipt line — use the quantity field for multiple units, never create duplicate rows
- All prices are ALWAYS output as POSITIVE numbers, including discounts and deposits

## ITEM FIELD RULES

### item_name — Receipt Text Cleaning
Extract the core product text from the receipt line. You must clean the string to ensure exact-matching in a database:

KEEP: brand name, product name, variant, size/packaging info (e.g., "500g", "1,5L PET", "6x33cl").

REMOVE: article codes, internal PLU numbers, and EAN/barcode numbers at the start of the line.

REMOVE: quantity counts, weight multipliers (e.g., "0,540 kg x"), unit prices, and total prices.

REMOVE: promotional symbols at the start of the text (e.g., *, +, >, P , PROMO).

REMOVE: Tax/VAT indicator letters or percentages at the end of the text (e.g., " A", " B", " C", " D", " 6%", " 21%").

FORMAT: Return the final cleaned string in ALL CAPS, with leading and trailing whitespace removed.

Examples:
- "A 14515 BONI BIO volkorenspaghetti 500g 1 0,99 0,99" → "BONI BIO VOLKORENSPAGHETTI 500G"
- "123456 COCA COLA ZERO 1,5L PET 2 3,58" → "COCA COLA ZERO 1,5L PET"
- "*PROMO DANONE ACTIVIA 4X125G B" → "DANONE ACTIVIA 4X125G"
- "0,540 kg x 5,99/kg BANANEN" → "BANANEN"

### normalized_name — Canonical Product Name
A clean, lowercase product name for EAN matching and deduplication. Rules:
- ALWAYS include the brand name (it is part of product identity)
- ALWAYS lowercase
- REMOVE: quantities (450ml, 1L, 500g, 6x33cl), packaging types (PET, Blik, Fles), receipt codes
- Keep the original language (Dutch or French — do not translate)
- CRITICAL consistency rule: the SAME product seen on different receipts must ALWAYS produce the EXACT SAME normalized_name

Examples:
- "JUPILER PILS 6X33CL PET" → "jupiler pils"
- "BONI VOLLE MELK 1L" → "boni volle melk"
- "COCA COLA ZERO 1,5L PET" → "coca-cola zero"
- For discount lines: describe the discount type, e.g. "korting hoeveelheidsvoordeel", "actieprijs", "lidl plus korting"

### normalized_brand — Brand Identification
Output brand/manufacturer name only, lowercase.

House brands by retailer (is_premium=false):
Colruyt: Boni, Boni Selection, Boni Bio, Everyday
Delhaize: 365, Delhaize, P'tits Lions
Carrefour: Simpl, Carrefour Bio, Carrefour Classic
Lidl: ALL sub-brands (Milbona, Pikok, Chef Select, Deluxe, Freeway, Vemondo, Solevita, Alesto, Snack Day, Combino, Trattoria Alfredo, Fin Carré, etc.)
Aldi: ALL sub-brands (Milsani, Moser Roth, Gourmet, Cucina, Lyttos, Barissimo, River, Sun Snacks, Bon Gelati, Choceur, etc.)
AH: AH, AH Basic, AH Excellent, Perla, Delicata
Jumbo: Jumbo
Intermarché: Top Budget, Pâturages

Rules:
- Brand = store chain name → always house brand
- Fresh/deli/bakery without visible brand → "in-house"
- Truly generic (loose fruit, bulk) → null

Receipt text → normalized_brand | is_premium
"JUPILER PILS" → "jupiler" | true
"MILBONA VOLLE MELK" → "milbona" | false
"KIP KYOTO MET RIJST" → "in-house" | false
"BANANEN 1KG" → null | false

### is_premium — Premium vs House Brand Flag
- true: premium/national brands (Coca-Cola, Jupiler, Danone, Lay's, Nestlé, Heinz, etc.)
- false: ALL house brands listed above, ALL Lidl/Aldi sub-brands, brand = store chain name

### Pricing Rules
- Belgian receipts use commas as decimal separators — always convert to dots: 2,99 → 2.99
- total_price is ALWAYS a positive float, for every line type including discounts and deposits
- For discount lines: total_price is the discount AMOUNT (the reduction value), as a positive number. e.g., "HOEVEELHEIDSVOORDEEL -0,60" → total_price = 0.60
- unit_price: only populate if the receipt explicitly shows a per-unit price separate from the total
- quantity: parse from "2x", "x3", "2 ST", etc. Default 1

## DISCOUNT LINE DETECTION

Discounts appear on SEPARATE receipt lines. Extract each line as its own item.

### Patterns (receipt → extraction)

| Receipt lines | → item 1 | → item 2 |
|---|---|---|
| `COCA COLA 3,58` / `HOEVEELHEIDSVOORDEEL -0,60` | product, 3.58 | discount, 0.60 |
| `PRODUCT 3,58` / `ACTIEPRIJS 2,98` | product, 3.58 | discount, 0.60 (=3.58−2.98) |
| `YOGHURT 2,49` ×2 / `2+1 GRATIS -2,49` | product ×2, 2.49 each | discount, 2.49 |
| `LIDL PLUS KORTING -1,20` (near subtotal) | — | discount, 1.20 |

### Discount output rules
- is_discount=true
- total_price = discount AMOUNT (positive)
- normalized_name = discount type (e.g. "korting hoeveelheidsvoordeel", "actieprijs")
- granular_category = "Discount"

### Terms → is_discount=true
NL: Hoeveelheidsvoordeel, Korting, Bon korting, Promotie, Actie, Actieprijs, Reductie, Rode prijs, Besparing, Voordeel, Aanbieding, Stuntprijs, Kwantiteitkorting, Xtra korting, SuperPlus korting, Lidl Plus korting, AH Bonus, Jumbo Extra's
FR: Prix rouge, Promo, Remise, Prix Choc, Carte Carrefour, Bon de réduction, DLC court
Multi-buy: 2+1 gratis, 1+1 gratis, 3=2, 2e aan halve prijs, 2ème à -50%, 2ème à moitié prix, Offert, Gratuit
Other: E-coupon, Leveranciersbon

### NOT discounts
- Deposits (leeggoed/statiegeld/vidange/consigne) → is_deposit
- Voucher payments (maaltijdcheques/titres-repas/ecocheques) → skip entirely

## DEPOSIT LINE DETECTION

Deposits are NOT products. Set is_deposit=true.

| Term | is_deposit | is_deposit_refund |
|---|---|---|
| Leeggoed, Statiegeld, Vidange, Consigne, Emballage | true | false |
| Retour leeggoed, Retour vidange, Retour consigne, Leeggoed retour | true | true |

## GRANULAR CATEGORIES

Assign ONE category from this list for each item. Use "Other" if nothing fits.

{categories}

For all discount lines (is_discount=true): always use granular_category "Discount".

## WEIGHED AND MEASURED ITEMS

For items sold by weight/volume (fruit, veg, deli, cheese):

Receipt text → unit_of_measure | weight_or_volume | price_per_unit_measure
"1.234 kg x 5.99/kg = 7.39" → kg | 1.234 | 5.99
"0.547 kg 3.28" → kg | 0.547 | null
"1.5 l" → l | 1.5 | null
Standard packaged items → null | null | null

## DATA PLATFORM FIELDS (dp_ prefix)

Populate for product lines only. null for discount/deposit lines.

dp_expanded_description: full product text, lowercase → "jupiler pils 6x33cl pet"
dp_pack_quantity: multi-pack count → "6X33CL"→6, "4x125g"→4, single→1
dp_per_item_size: ONE item size, raw number, do NOT multiply by pack qty → "6X33CL"→33, "1,5L"→1.5, "500g"→500
dp_pack_unit: unit as printed, lowercase: "cl","ml","l","g","kg". Do NOT convert units
dp_product_variant: flavor/sub-type, lowercase → "zero","bruin","paprika","pils". null if base product
dp_article_code: article/PLU/EAN from receipt → "ART 123456","PLU 4011". null if not visible
dp_is_bio: BIO/BIOLOGISCH/BIOLOGIQUE/ORGANIC in text → true, else false

Extract all line items from this receipt.'''

    def __init__(self):
        self.client = _get_gemini_client()

    async def extract_receipt(self, file_content: bytes, user_id: str) -> GeminiExtractionResult:
        """Extract and normalize receipt data using Gemini Vision.

        Passes the PDF inline to avoid the Files API upload round-trip.
        A per-user semaphore limits concurrent generate_content calls to prevent
        API-side queuing that compounds latency under concurrent uploads.
        """
        content_size = len(file_content)
        if content_size > self.MAX_FILE_SIZE:
            size_mb = content_size / (1024 * 1024)
            raise GeminiAPIError(
                f"Receipt file too large ({size_mb:.1f}MB). Maximum is 5MB.",
                details={"error_type": "file_too_large", "size_bytes": content_size},
            )

        system_prompt = (
            self.SYSTEM_PROMPT
            .replace("{categories}", CATEGORIES_PROMPT_LIST)
            .replace("{stores}", STORES_PROMPT_LIST)
        )

        logger.info(
            f"Gemini extraction starting: content_size={content_size} bytes, "
            f"model={self.MODEL}, max_tokens={self.MAX_TOKENS}, user_id={user_id}"
        )

        if not settings.GEMINI_API_KEY:
            raise GeminiAPIError("GEMINI_API_KEY not configured", details={"error_type": "config"})

        content_part = types.Part.from_bytes(data=file_content, mime_type="application/pdf")

        response_text = None
        try:
            t0 = time.monotonic()
            async with _gemini_semaphore:
                semaphore_wait = time.monotonic() - t0
                if semaphore_wait > 0.1:
                    logger.info(f"⏱ semaphore_wait: {semaphore_wait:.3f}s (global concurrency limit reached)")
                t1 = time.monotonic()
                response = await self.client.aio.models.generate_content(
                    model=self.MODEL,
                    contents=[content_part],
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        max_output_tokens=self.MAX_TOKENS,
                        temperature=1.0,
                        thinking_config=types.ThinkingConfig(thinking_level="low"),
                        response_mime_type="application/json",
                        response_schema=_ReceiptSchema,
                        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
                    ),
                )
            generate_elapsed = time.monotonic() - t1
            um = getattr(response, 'usage_metadata', None)
            tokens = (
                f"in={getattr(um, 'prompt_token_count', '?')}, "
                f"out={getattr(um, 'candidates_token_count', '?')}, "
                f"total={getattr(um, 'total_token_count', '?')}"
            ) if um else "no usage data"
            logger.info(
                f"⏱ gemini_generate_content: {generate_elapsed:.1f}s, "
                f"tokens=[{tokens}], "
                f"finish_reason={response.candidates[0].finish_reason if response.candidates else 'N/A'}"
            )

            # Check for safety-blocked responses before accessing .text (can hang indefinitely)
            if response.candidates and response.candidates[0].finish_reason:
                finish_reason = str(response.candidates[0].finish_reason)
                if "SAFETY" in finish_reason or "BLOCKED" in finish_reason:
                    raise GeminiAPIError(
                        "Receipt image was blocked by safety filters",
                        details={"error_type": "safety_blocked", "finish_reason": finish_reason},
                    )
                if "MAX_TOKENS" in finish_reason or "LENGTH" in finish_reason:
                    logger.warning(
                        f"Gemini response truncated (finish_reason={finish_reason}). "
                        f"Receipt may have too many items for current token limit."
                    )

            response_text = response.text
            if not response_text:
                raise GeminiAPIError(
                    "Gemini returned empty response",
                    details={"error_type": "empty_response"},
                )

            data = json.loads(response_text)
            logger.info(
                f"Gemini response parsed: vendor={data.get('vendor_name')}, "
                f"items={len(data.get('line_items', []))}, "
                f"date={data.get('receipt_date')}, total={data.get('total')}"
            )

            return self._build_result(data)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response as JSON: {e}")
            raise GeminiAPIError(
                "Failed to parse extraction response",
                details={"error_type": "parse_error", "parse_error": str(e)},
            )
        except GeminiAPIError:
            raise
        except genai_errors.APIError as e:
            elapsed = time.monotonic() - t0
            logger.error(f"Gemini API error after {elapsed:.1f}s: code={e.code}, message={e.message}")
            raise GeminiAPIError(
                f"Gemini API error: {e.message}",
                details={"error_type": "api_error", "status_code": e.code, "message": e.message},
            )
        except Exception as e:
            elapsed = time.monotonic() - t0
            logger.exception(f"Extraction failed after {elapsed:.1f}s: {type(e).__name__}: {e}")
            raise GeminiAPIError(
                f"Extraction failed: {str(e)}",
                details={"error_type": "unexpected", "error_class": type(e).__name__, "error": str(e)},
            )

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
                total_price = abs(float(total_price))  # Always positive
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

            # Deterministic pack size: LLM returns per-item size + raw unit,
            # we convert units and multiply by quantity here.
            dp_per_item_size = item.get("dp_per_item_size")
            raw_unit = item.get("dp_pack_unit")
            if dp_per_item_size is not None:
                try:
                    dp_per_item_size = float(dp_per_item_size)
                except (ValueError, TypeError):
                    dp_per_item_size = None

            if raw_unit:
                raw_unit = raw_unit.lower().strip()

            if dp_per_item_size is not None and raw_unit in _UNIT_CONVERSIONS:
                target_unit, factor = _UNIT_CONVERSIONS[raw_unit]
                qty = dp_pack_quantity or 1
                dp_pack_size = dp_per_item_size * factor * qty
                dp_pack_unit = target_unit
            else:
                dp_pack_size = None
                dp_pack_unit = None

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
                    is_deposit_refund=bool(item.get("is_deposit_refund", False)),
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
            store_branch=store_branch,
        )


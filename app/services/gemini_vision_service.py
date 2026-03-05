"""
Gemini Vision service for receipt OCR and semantic line item extraction.

Replaces Veryfi for OCR extraction and handles:
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
    store_branch: Optional[str]  # store location/branch


# Pydantic schemas passed as response_schema to Gemini — structurally constrains the JSON output
# so the model cannot return a bare array instead of the expected object.
class _LineItemSchema(PydanticBaseModel):
    item_name: str = Field(
        description=(
            "Product text from the receipt line in ORIGINAL casing. "
            "Keep brand, name, variant, size/packaging info. "
            "Remove article codes, PLU numbers, quantity counts, unit prices, and total prices. "
            "Examples: 'A 14515 BONI BIO volkorenspaghetti 500g 1 0,99 0,99' → 'BONI BIO volkorenspaghetti 500g', "
            "'123456 COCA COLA ZERO 1,5L PET 2 3,58' → 'COCA COLA ZERO 1,5L PET'"
        )
    )
    normalized_name: str = Field(
        description=(
            "Clean product name for EAN matching, ALWAYS lowercase. "
            "ALWAYS keep brand name (it is part of product identity). "
            "Remove quantities (450ml, 1L, 500g, 6x33cl), packaging types (PET, Blik, Fles), and receipt codes. "
            "Keep original language (Dutch/French). "
            "CRITICAL: the SAME product must ALWAYS produce the SAME normalized_name. "
            "Examples: 'JUPILER PILS 6X33CL PET' → 'jupiler pils', "
            "'BONI VOLLE MELK 1L' → 'boni volle melk', "
            "'COCA COLA ZERO 1,5L PET' → 'coca-cola zero'"
        )
    )
    normalized_brand: Optional[str] = Field(
        default=None,
        description=(
            "Brand/manufacturer name only, lowercase. NOT the store chain name. "
            "For store/house brands, use the house brand name: "
            "Colruyt: Boni, Boni Selection, Boni Bio, Everyday. "
            "Delhaize: 365, Delhaize, P'tits Lions. "
            "Carrefour: Simpl, Carrefour Bio, Carrefour Classic. "
            "ALL Lidl sub-brands are house brands (Milbona, Pikok, Chef Select, Deluxe, Freeway, Vemondo, Solevita, Alesto, Snack Day, Combino, Trattoria Alfredo, Fin Carré, etc.). "
            "ALL Aldi sub-brands are house brands (Milsani, Moser Roth, Gourmet, Cucina, Lyttos, Barissimo, River, Sun Snacks, Bon Gelati, Choceur, etc.). "
            "AH: AH, AH Basic, AH Excellent, Perla, Delicata. Jumbo: Jumbo. Intermarché: Top Budget, Pâturages. "
            "Brands matching the store name (Delhaize, Carrefour, AH, Jumbo) are always house brands. "
            "For fresh/deli/bakery items without a visible brand, use 'in-house'. "
            "null only for truly generic items (loose fruit, vegetables by weight). "
            "Examples: 'JUPILER PILS' → 'jupiler', 'MILBONA VOLLE MELK' → 'milbona', 'KIP KYOTO MET RIJST' → 'in-house', 'BANANEN 1KG' → null"
        )
    )
    is_premium: bool = Field(
        description=(
            "true for premium/name brands (Coca-Cola, Jupiler, Danone, Lay's, Nestlé, Heinz). "
            "false for store/house brands (Boni, 365, Everyday, Simpl, Delhaize, P'tits Lions, "
            "Milbona, Pikok, Chef Select, Milsani, Moser Roth, AH, AH Basic, Perla, Jumbo, Top Budget, Cara) "
            "and unbranded items. All Lidl and Aldi sub-brands are house brands. "
            "Brands named after the store (Delhaize, Carrefour, AH, Jumbo) are house brands."
        )
    )
    quantity: int = Field(
        description="Number of items — parse from '2x', 'x3', '2 ST', etc. Default 1"
    )
    unit_price: Optional[float] = Field(
        default=None,
        description="Price per single item if shown separately on receipt"
    )
    total_price: float = Field(
        description=(
            "Total line price as a POSITIVE number. Convert Belgian comma decimals to dots (2,99 → 2.99). "
            "ALWAYS positive — even for discount and deposit lines. "
            "For discount lines, total_price is the discount AMOUNT (the reduction), as a positive number"
        )
    )
    is_discount: bool = Field(
        description=(
            "true for discount/bonus lines: Hoeveelheidsvoordeel, Korting, Bon korting, Promotie, Actie, Actieprijs, Reductie, "
            "Rode prijs, Prix rouge, Besparing, Voordeel, Promo, Aanbieding, Remise, Stuntprijs, Prix Choc, "
            "2+1 gratis, 1+1 gratis, 3=2, 2e aan halve prijs, 2ème à -50%, Offert, Gratuit, Kwantiteitkorting, "
            "Xtra korting, SuperPlus korting, Lidl Plus korting, AH Bonus, Jumbo Extra's, "
            "Carte Carrefour, Bon de réduction, DLC court, "
            "Leveranciersbon, E-coupon — any line that represents a price reduction. "
            "NEVER mark deposit/leeggoed/vidange lines as discount — use is_deposit instead. "
            "Set normalized_name to describe the discount (e.g. 'korting hoeveelheidsvoordeel', 'rode prijs', 'lidl plus korting')"
        )
    )
    is_deposit: bool = Field(
        description=(
            "true for ANY deposit-related line — both deposit charges (buying containers) and deposit refunds (returning containers). "
            "Dutch: Leeggoed, Statiegeld. French: Vidange, Consigne, Emballage. "
            "These are NOT actual product purchases"
        )
    )
    is_deposit_refund: bool = Field(
        description=(
            "true ONLY when the customer is receiving money back for returning containers. "
            "Receipt text: 'Retour leeggoed', 'Retour vidange', 'Retour consigne', 'Leeggoed retour'. "
            "false for deposit charges (buying new containers) and all non-deposit lines"
        )
    )
    granular_category: str = Field(
        description=(
            "One category from the provided category list — must be one of the exact category names, or 'Other'. "
            "For discount lines (is_discount=true), use: 'Discount' (general/korting/remise), "
            "'Coupon' (leveranciersbon/bon de réduction/e-coupon), "
            "'Loyalty Discount' (Lidl Plus/SuperPlus/Xtra/Carte Carrefour/AH Bonuskaart/Jumbo Extra's/Avantage Carte), "
            "'Promotional Offer' (actieprijs/promo/rode prijs/prix rouge/aanbieding), "
            "or 'Multi-Buy Deal' (2+1/1+1/3=2/gratis/offert/kwantiteitkorting/réduction de quantité). "
            "Important Exclusions: Do not classify bottle returns/deposits (leeggoed/statiegeld/vidange) "
            "or voucher payments (maaltijdcheques/titres-repas/ecocheques) as discounts."
        )
    )
    unit_of_measure: Optional[str] = Field(
        default=None,
        description=(
            "Unit for weighed/measured items: kg, g, l, ml, or piece. "
            "Look for per-kg/per-liter pricing lines (e.g. '1.234 kg x 5.99/kg'). "
            "null for standard packaged items"
        )
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
        description="Article/PLU/EAN/barcode from receipt ('ART 123456', 'PLU 4011'). null if not visible"
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
    store_branch: Optional[str] = Field(
        default=None,
        description="Store location/branch (city or street), NOT the chain name. e.g., 'Colruyt Leuven' → 'Leuven'"
    )
    total: Optional[float] = Field(
        default=None,
        description="Total amount printed on the receipt — the net amount the customer paid"
    )
    line_items: list[_LineItemSchema] = Field(
        description="All extracted line items. Include discount and deposit lines (all prices positive). Skip subtotals, totals, and payment lines"
    )


class GeminiVisionService:
    """Gemini Vision integration for receipt OCR and extraction."""

    MODEL = "gemini-3.1-pro-preview"
    MAX_TOKENS = 32000  # Actual output ~6k tokens + capped thinking budget; pro model supports 64k output
    MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB — Gemini inline data limit

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

### Store Branch
- Extract the store location/branch (the city, street, or branch identifier)
- This is the location part of the store name, NOT the store chain name
- Examples: "Colruyt Leuven" → "Leuven", "Delhaize Etterbeek" → "Etterbeek"
- Return null if no branch/location is found

### IMPORTANT RULES
- INCLUDE discount/bonus lines and deposit lines — extract ALL prices as POSITIVE values
- Skip subtotals, totals, payment lines, VAT summary lines
- One line item per receipt line — use the quantity field for multiples, do not create duplicate rows

### Belgian Receipt Promotion Patterns
Belgian receipts show discounts on SEPARATE lines below the product, never inline. Always extract each receipt line as its own line item.

Common patterns — extract each line as a SEPARATE item:
- **Product + discount line**: Product at full price on line 1, discount on line 2 (often indented). Extract both: product (is_discount=false) + discount (is_discount=true, total_price = discount amount).
  e.g. "COCA COLA 3,58" then "HOEVEELHEIDSVOORDEEL -0,60" → two items (3.58 + 0.60)
- **Product + Actieprijs line**: Product at original price, then "ACTIEPRIJS" with promo price on next line. Extract both: product at original price (is_discount=false) + discount line with total_price = original minus promo price (is_discount=true).
  e.g. "PRODUCT 3,58" then "ACTIEPRIJS 2,98" → product at 3.58 + discount at 0.60
- **Multi-buy discounts**: Multiple products then a combined discount line.
  e.g. "YOGHURT 2,49" twice then "2+1 GRATIS -2,49" → three items
- **Loyalty discounts at receipt bottom**: Lidl Plus, SuperPlus, Xtra, Carte Carrefour discounts grouped near the subtotal — extract each as a discount line with granular_category "Loyalty Discount".

For discount lines: set is_discount=true, normalized_name describes the discount type (e.g. "korting hoeveelheidsvoordeel", "actieprijs", "lidl plus korting").

### Granular Categories
Assign ONE category from this list for each item:
{categories}

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
                f"Receipt file too large ({size_mb:.1f}MB). Maximum is 20MB.",
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

        # Verify API key is set
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            logger.error("GEMINI_API_KEY is not set!")
            raise GeminiAPIError("GEMINI_API_KEY not configured", details={"error_type": "config"})
        logger.info(f"API key present: {api_key[:8]}...{api_key[-4:]} (length={len(api_key)})")

        content_part = types.Part.from_bytes(data=file_content, mime_type="application/pdf")
        logger.info(f"Using inline PDF ({content_size} bytes)")

        response_text = None
        try:
            t0 = time.monotonic()
            async with _get_user_semaphore(user_id):
                semaphore_wait = time.monotonic() - t0
                if semaphore_wait > 0.1:
                    logger.info(f"⏱ semaphore_wait: {semaphore_wait:.3f}s (another request was in progress)")
                t1 = time.monotonic()
                response = await asyncio.wait_for(
                    self.client.aio.models.generate_content(
                        model=self.MODEL,
                        contents=[content_part],
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

            # Log response metadata
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


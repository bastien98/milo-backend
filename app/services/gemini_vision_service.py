"""
Gemini Vision service for receipt OCR and semantic line item extraction.

Replaces Veryfi for OCR extraction and handles:
- Line item extraction with normalized names
- Belgian pricing conventions (comma→dot, Hoeveelheidsvoordeel)
- Deposit item detection (Leeggoed/Vidange)
- Granular categorization (~200 categories)
- Health scoring
"""

import io
import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

from google import genai
from google.genai import types
from PIL import Image

from app.core.exceptions import GeminiAPIError
from app.config import get_settings
from app.services.categories import CATEGORIES_PROMPT_LIST, GRANULAR_CATEGORIES, get_parent_category

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class ExtractedLineItem:
    """Represents a line item extracted and normalized by Gemini Vision."""

    original_description: str  # Raw OCR text
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
    health_score: Optional[int]  # 0-5, None for non-foobrandd
    unit_of_measure: Optional[str]  # kg/g/l/ml/piece
    weight_or_volume: Optional[float]  # actual weight/volume
    price_per_unit_measure: Optional[float]  # price per kg/liter


@dataclass
class GeminiExtractionResult:
    """Complete extraction result from Gemini Vision."""

    vendor_name: str
    receipt_date: Optional[date]
    total: Optional[float]
    line_items: list[ExtractedLineItem]
    ocr_text: Optional[str]  # Full OCR for debugging
    receipt_time: Optional[str]  # HH:MM format
    payment_method: Optional[str]  # bancontact/visa/mastercard/cash/payconiq/meal_vouchers/mixed
    total_savings: Optional[float]  # total discount amount (positive number)
    store_branch: Optional[str]  # store location/branch


class GeminiVisionService:
    """Gemini Vision integration for receipt OCR and extraction."""

    MODEL = "gemini-2.5-flash-preview-09-2025"
    MAX_TOKENS = 16384

    SYSTEM_PROMPT = '''You are a Belgian grocery receipt analyzer. Extract and normalize line items from receipt images.

## EXTRACTION RULES

### Vendor Name
- Clean OCR artifacts, use proper store name
- Common Belgian stores: Colruyt, Delhaize, Carrefour, Aldi, Lidl, Albert Heijn

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

1. **original_description**: Raw text exactly as appears on receipt (including codes, quantities, etc.)

2. **normalized_name**: Clean, generic product name following these rules:
   - ALWAYS output in **lowercase**
   - REMOVE quantities (450ml, 1L, 500g, 10st, 6x33cl, etc.)
   - REMOVE packaging types (PET, Blik, Fles, Doos, Brik, etc.)
   - REMOVE ALL brand/manufacturer names from normalized_name — brands go ONLY in normalized_brand:
     - Remove store/house brands: Boni, 365, Everyday, Cara, etc.
     - Remove manufacturer brands: Vandemoortele, Dr. Oetker, Nestlé, Heinz, Devos Lemmens, Lay's, Duyvis, etc.
   - EXCEPTION: Keep the brand ONLY when it IS the product identity (removing it leaves no meaningful name):
     - Keep: "jupiler" (without brand = just "bier pils", too generic)
     - Keep: "coca-cola zero" (without brand = "cola zero", too generic)
     - Keep: "leffe bruin" (without brand = "abdijbier bruin", nobody says that)
     - Keep: "nutella" (without brand = "hazelnootpasta", different identity)
   - Keep the product's natural word order as on the receipt (after removing brand/quantities)
   - DO NOT reorder product words — strip brand + quantities and keep the remaining order
   - Maintain original language (Dutch/French)
   - **CRITICAL**: The SAME product must ALWAYS produce the SAME normalized_name, regardless of receipt format or OCR variations
   - Examples:
     - "JUPILER BIER 6X33CL PET" → "jupiler" (brand IS the product)
     - "BONI VOLLE MELK 1L" → "volle melk" (house brand removed)
     - "COCA COLA ZERO 1,5L PET" → "coca-cola zero" (brand IS the product)
     - "VANDEMOORTELE VINAIGRETTE CAESAR 450ML" → "vinaigrette caesar" (manufacturer removed, word order preserved)
     - "LEFFE BRUIN 6X33CL" → "leffe bruin" (brand IS the product)
     - "DR. OETKER CASA DI MAMA SALAME 390G" → "casa di mama salame" (manufacturer removed, sub-brand kept)
     - "LAY'S CHIPS PAPRIKA 250G" → "chips paprika" (manufacturer removed)
     - "DEVOS LEMMENS MAYONAISE 300ML" → "mayonaise" (manufacturer removed)
     - "DUYVIS BORRELNOOTJES HOT 275G" → "borrelnootjes hot" (manufacturer removed)

3. **normalized_brand**: The brand/manufacturer name ONLY, in **lowercase**. MUST always be set when a brand is identifiable.
   - Extract the product's brand/manufacturer, NOT the store name
   - For store/house brands (Boni, 365, Everyday, Cara, Delhaize brand), use the house brand name
   - If no brand is identifiable, use null
   - IMPORTANT: normalized_brand must be set even when the brand was kept in normalized_name
   - Examples:
     - "JUPILER BIER 6X33CL PET" → "jupiler"
     - "BONI VOLLE MELK 1L" → "boni"
     - "COCA COLA ZERO 1,5L PET" → "coca-cola"
     - "VANDEMOORTELE VINAIGRETTE CAESAR 450ML" → "vandemoortele"
     - "LEFFE BRUIN 6X33CL" → "leffe"
     - "LAY'S CHIPS PAPRIKA 250G" → "lay's"
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

### IMPORTANT RULES
- INCLUDE discount/bonus lines with NEGATIVE total_price values (these reduce the receipt total)
- Skip subtotals, totals, payment lines
- Each product should appear ONCE even if the receipt shows quantity
- For multi-section receipts with overlapping items, deduplicate by product name

### Granular Categories
Assign ONE category from this list for each item:
{categories}

### Health Scores (0-5)
- 5: Fresh vegetables, fruits, water, plain nuts
- 4: Whole grains, lean proteins, eggs, plain dairy
- 3: Bread, pasta, cheese, some ready meals
- 2: Processed meats, sweetened drinks, some snacks
- 1: Chips, candy, cookies, sodas, sugary cereals
- 0: Alcohol, energy drinks, heavily processed foods
- null: Non-food items (household, personal care, pet supplies)

## OUTPUT FORMAT
Return a JSON object with this structure:
- "vendor_name": string
- "receipt_date": "YYYY-MM-DD"
- "receipt_time": "HH:MM" or null
- "payment_method": string or null (bancontact/visa/mastercard/cash/payconiq/meal_vouchers/mixed)
- "total_savings": number or null (positive, sum of all discount amounts)
- "store_branch": string or null (location/branch name)
- "total": number (receipt total)
- "line_items": array of objects, each with:
  - "original_description": string (raw OCR text)
  - "normalized_name": string (cleaned name, lowercase)
  - "normalized_brand": string or null
  - "is_premium": boolean
  - "quantity": integer
  - "unit_price": number or null
  - "total_price": number (negative for discounts)
  - "is_discount": boolean
  - "is_deposit": boolean
  - "granular_category": string (from list above)
  - "health_score": integer 0-5 or null
  - "unit_of_measure": string or null (kg/g/l/ml/piece)
  - "weight_or_volume": number or null
  - "price_per_unit_measure": number or null'''

    # Image compression settings (for large images only)
    MAX_IMAGE_SIZE = (1600, 2400)  # Max dimensions for compressed image
    JPEG_QUALITY = 85  # JPEG compression quality

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("Gemini API key not configured")
        self.client = genai.Client(api_key=self.api_key)

    def _compress_image(self, image_content: bytes, mime_type: str) -> tuple[bytes, str]:
        """Compress image if it's too large.

        Returns:
            Tuple of (compressed image bytes, mime_type)
        """
        try:
            # Only compress if larger than 500KB
            if len(image_content) < 500_000:
                return image_content, mime_type

            img = Image.open(io.BytesIO(image_content))

            # Convert to RGB if necessary (for PNG with transparency)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            # Resize if too large
            img.thumbnail(self.MAX_IMAGE_SIZE, Image.Resampling.LANCZOS)

            # Compress to JPEG
            output = io.BytesIO()
            img.save(output, format="JPEG", quality=self.JPEG_QUALITY, optimize=True)
            compressed_bytes = output.getvalue()

            logger.info(
                f"Image compressed: {len(image_content)} bytes → {len(compressed_bytes)} bytes "
                f"({len(compressed_bytes) / len(image_content) * 100:.1f}%)"
            )

            return compressed_bytes, "image/jpeg"

        except Exception as e:
            logger.warning(f"Image compression failed, using original: {e}")
            return image_content, mime_type

    async def extract_receipt(
        self, file_content: bytes, mime_type: str
    ) -> GeminiExtractionResult:
        """Extract and normalize receipt data using Gemini Vision.

        PDFs are converted to compressed images for better reliability.
        Large images are also compressed.
        """

        # Build prompt with shared category list
        system_prompt = self.SYSTEM_PROMPT.format(categories=CATEGORIES_PROMPT_LIST)

        # Log input details for debugging
        logger.info(f"Gemini extraction: mime_type={mime_type}, content_size={len(file_content)} bytes")

        # Pass PDFs directly to Gemini, compress large images only
        if mime_type == "application/pdf":
            processed_content, processed_mime = file_content, mime_type
        else:
            processed_content, processed_mime = self._compress_image(file_content, mime_type)

        extract_prompt = "Extract all line items from this receipt image. Return JSON only."

        try:
            response = self.client.models.generate_content(
                model=self.MODEL,
                contents=[
                    types.Part.from_bytes(
                        data=processed_content,
                        mime_type=processed_mime,
                    ),
                    extract_prompt,
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=self.MAX_TOKENS,
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )

            # Parse response - JSON mode guarantees valid JSON
            response_text = response.text
            if not response_text:
                logger.error(f"Gemini returned empty response. Candidates: {getattr(response, 'candidates', 'N/A')}")
                if hasattr(response, 'prompt_feedback'):
                    logger.error(f"Prompt feedback: {response.prompt_feedback}")
                raise GeminiAPIError(
                    "Gemini returned empty response",
                    details={"error_type": "empty_response"},
                )
            data = json.loads(response_text)

            # Debug logging to see what Gemini returned
            logger.info(f"Gemini response parsed: vendor={data.get('vendor_name')}, items={len(data.get('line_items', []))}")
            if data.get('line_items'):
                first_item = data['line_items'][0]
                logger.info(f"First item sample: original_desc={first_item.get('original_description')}, "
                           f"normalized={first_item.get('normalized_name')}, "
                           f"granular_cat={first_item.get('granular_category')}")

            return self._build_result(data)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response: {e}")
            logger.error(f"Raw response: {response_text[:500] if response_text else 'empty'}")
            raise GeminiAPIError(
                "Failed to parse extraction response",
                details={"error_type": "parse_error", "parse_error": str(e)},
            )
        except Exception as e:
            logger.exception(f"Extraction failed: {e}")
            raise GeminiAPIError(
                f"Extraction failed: {str(e)}",
                details={"error_type": "unexpected", "error": str(e)},
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

            # Parse health score
            health_score_raw = item.get("health_score")
            if health_score_raw is not None:
                health_score = max(0, min(5, int(health_score_raw)))
            else:
                health_score = None

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

            line_items.append(
                ExtractedLineItem(
                    original_description=item.get("original_description", ""),
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
                    health_score=health_score,
                    unit_of_measure=unit_of_measure,
                    weight_or_volume=weight_or_volume,
                    price_per_unit_measure=price_per_unit_measure,
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
            ocr_text=data.get("ocr_text"),
            receipt_time=receipt_time,
            payment_method=payment_method,
            total_savings=total_savings,
            store_branch=store_branch,
        )

"""
Mistral Document AI service for receipt OCR and semantic line item extraction.

Uses the Document QnA approach: chat.complete() with document_url content type.
Mistral runs OCR internally, then the LLM extracts structured data via JSON mode.

Drop-in replacement for GeminiVisionService — returns the same dataclass types.
"""

import base64
import io
import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

from mistralai import Mistral
from PIL import Image

from app.config import get_settings
from app.core.categories import CATEGORIES_PROMPT_LIST, GRANULAR_CATEGORIES, get_parent_category
from app.core.exceptions import GeminiAPIError  # Reuse existing exception class
from app.services.gemini_vision_service import ExtractedLineItem

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class MistralExtractionResult:
    """Complete extraction result from Mistral Document AI."""

    vendor_name: str
    receipt_date: Optional[date]
    total: Optional[float]
    line_items: list[ExtractedLineItem]
    ocr_text: Optional[str]
    receipt_time: Optional[str]
    payment_method: Optional[str]
    total_savings: Optional[float]
    store_branch: Optional[str]


class MistralDocumentService:
    """Mistral Document AI integration for receipt OCR and extraction.

    Uses the Document QnA approach: sends the receipt as a document/image
    to chat.complete(), which runs OCR internally then extracts structured
    data via JSON mode with the same prompt as GeminiVisionService.
    """

    MODEL = "mistral-small-latest"
    MAX_TOKENS = 32768

    # Same system prompt as GeminiVisionService
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
   - If no brand is identifiable, use null
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

17. **dp_packaging_type**: Container type (lowercase): blik/pet/fles/doos/brik/glas/zak. Parse from "PET","BLIK","BL.","FLES","FL." etc. null if not mentioned.

18. **dp_product_variant**: Flavor/style/sub-type (lowercase). "zero","bruin","paprika","pils". null if base product.

19. **dp_article_code**: Article/PLU/barcode from receipt ("ART 123456", "PLU 4011"). null if not visible.

20. **dp_is_bio**: true if BIO/BIOLOGISCH/BIOLOGIQUE/ORGANIC in text, false otherwise.

## FEW-SHOT EXAMPLES

### Example 1: Multi-pack with packaging + dp_ fields
"JUPILER PILS 6X33CL PET  8,99" →
```json
{"original_description":"JUPILER PILS 6X33CL PET  8,99","normalized_name":"jupiler pils","normalized_brand":"jupiler","is_premium":true,"quantity":1,"unit_price":null,"total_price":8.99,"is_discount":false,"is_deposit":false,"granular_category":"Beer Pils & Lager","health_score":0,"unit_of_measure":null,"weight_or_volume":null,"price_per_unit_measure":null,"dp_expanded_description":"jupiler pils 6x33cl pet","dp_pack_quantity":6,"dp_pack_size":1980.0,"dp_pack_unit":"ml","dp_packaging_type":"pet","dp_product_variant":"pils","dp_article_code":null,"dp_is_bio":false}
```

### Example 2: Fresh produce by weight
"BANANEN  1.234 kg x 1,99/kg  2,46" →
```json
{"original_description":"BANANEN  1.234 kg x 1,99/kg  2,46","normalized_name":"bananen","normalized_brand":null,"is_premium":false,"quantity":1,"unit_price":null,"total_price":2.46,"is_discount":false,"is_deposit":false,"granular_category":"Fruit Bananas","health_score":5,"unit_of_measure":"kg","weight_or_volume":1.234,"price_per_unit_measure":1.99,"dp_expanded_description":"bananen","dp_pack_quantity":1,"dp_pack_size":1234.0,"dp_pack_unit":"g","dp_packaging_type":null,"dp_product_variant":null,"dp_article_code":null,"dp_is_bio":false}
```

### Example 3: Discount line (negative price)
"HOEVEELHEIDSVOORDEEL  -1,50" →
```json
{"original_description":"HOEVEELHEIDSVOORDEEL  -1,50","normalized_name":"korting hoeveelheidsvoordeel","normalized_brand":null,"is_premium":false,"quantity":1,"unit_price":null,"total_price":-1.50,"is_discount":true,"is_deposit":false,"granular_category":"Other","health_score":null,"unit_of_measure":null,"weight_or_volume":null,"price_per_unit_measure":null,"dp_expanded_description":"hoeveelheidsvoordeel","dp_pack_quantity":null,"dp_pack_size":null,"dp_pack_unit":null,"dp_packaging_type":null,"dp_product_variant":null,"dp_article_code":null,"dp_is_bio":false}
```

### Example 4: Product with article code
"ART 541014  DEVOS LEMMENS MAYO 300ML  2,49" →
```json
{"original_description":"ART 541014  DEVOS LEMMENS MAYO 300ML  2,49","normalized_name":"devos lemmens mayonaise","normalized_brand":"devos lemmens","is_premium":true,"quantity":1,"unit_price":null,"total_price":2.49,"is_discount":false,"is_deposit":false,"granular_category":"Mayonnaise","health_score":2,"unit_of_measure":null,"weight_or_volume":null,"price_per_unit_measure":null,"dp_expanded_description":"devos lemmens mayonaise 300ml","dp_pack_quantity":1,"dp_pack_size":300.0,"dp_pack_unit":"ml","dp_packaging_type":null,"dp_product_variant":null,"dp_article_code":"541014","dp_is_bio":false}
```

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
  - "price_per_unit_measure": number or null
  - "dp_expanded_description": string or null (full product text for vector search)
  - "dp_pack_quantity": integer or null (multi-pack count, 1 for singles)
  - "dp_pack_size": number or null (total pack size in ml or g)
  - "dp_pack_unit": string or null ("ml" or "g")
  - "dp_packaging_type": string or null (blik/pet/fles/doos/brik/glas/zak)
  - "dp_product_variant": string or null (flavor/style/sub-type)
  - "dp_article_code": string or null (article/PLU code from receipt)
  - "dp_is_bio": boolean (true if organic)'''

    # Image compression settings (same as Gemini service)
    MAX_IMAGE_SIZE = (1600, 2400)
    JPEG_QUALITY = 85

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.MISTRAL_API_KEY
        if not self.api_key:
            raise ValueError("Mistral API key not configured")
        self.client = Mistral(api_key=self.api_key)

    def _compress_image(self, image_content: bytes, mime_type: str) -> tuple[bytes, str]:
        """Compress image if it's too large."""
        try:
            if len(image_content) < 500_000:
                return image_content, mime_type

            img = Image.open(io.BytesIO(image_content))
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            img.thumbnail(self.MAX_IMAGE_SIZE, Image.Resampling.LANCZOS)

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
    ) -> MistralExtractionResult:
        """Extract and normalize receipt data using Mistral Document AI.

        Uses the Document QnA approach: sends the receipt as base64-encoded
        content to chat.complete(), which runs OCR internally then extracts
        structured data via JSON mode.
        """
        system_prompt = self.SYSTEM_PROMPT.replace("{categories}", CATEGORIES_PROMPT_LIST)

        logger.info(f"Mistral extraction: mime_type={mime_type}, content_size={len(file_content)} bytes")

        # Compress large images (PDFs sent as-is)
        if mime_type == "application/pdf":
            processed_content, processed_mime = file_content, mime_type
        else:
            processed_content, processed_mime = self._compress_image(file_content, mime_type)

        # Base64 encode the content for the data URI
        b64_content = base64.b64encode(processed_content).decode("utf-8")

        # Build the content block based on file type
        if mime_type == "application/pdf":
            document_block = {
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{b64_content}",
            }
        else:
            document_block = {
                "type": "image_url",
                "image_url": f"data:{processed_mime};base64,{b64_content}",
            }

        messages = [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Extract all line items from this receipt image. Return JSON only.",
                    },
                    document_block,
                ],
            },
        ]

        try:
            response = self.client.chat.complete(
                model=self.MODEL,
                messages=messages,
                max_tokens=self.MAX_TOKENS,
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            # Log token usage
            if response.usage:
                logger.info(
                    f"Mistral token usage: "
                    f"input={response.usage.prompt_tokens}, "
                    f"output={response.usage.completion_tokens}, "
                    f"total={response.usage.total_tokens}"
                )

            # Check for truncation
            if response.choices and response.choices[0].finish_reason:
                finish_reason = response.choices[0].finish_reason
                if finish_reason == "length":
                    logger.warning(
                        f"Mistral response truncated (finish_reason={finish_reason}). "
                        f"Receipt may have too many items for current token limit."
                    )

            response_text = response.choices[0].message.content if response.choices else None
            if not response_text:
                logger.error(f"Mistral returned empty response. Choices: {response.choices}")
                raise GeminiAPIError(
                    "Mistral returned empty response",
                    details={"error_type": "empty_response"},
                )

            data = json.loads(response_text)

            logger.info(
                f"Mistral response parsed: vendor={data.get('vendor_name')}, "
                f"items={len(data.get('line_items', []))}"
            )
            if data.get("line_items"):
                first_item = data["line_items"][0]
                logger.info(
                    f"First item sample: original_desc={first_item.get('original_description')}, "
                    f"normalized={first_item.get('normalized_name')}, "
                    f"granular_cat={first_item.get('granular_category')}"
                )

            return self._build_result(data)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Mistral response: {e}")
            logger.error(f"Raw response: {response_text[:500] if response_text else 'empty'}")
            raise GeminiAPIError(
                "Failed to parse extraction response",
                details={"error_type": "parse_error", "parse_error": str(e)},
            )
        except Exception as e:
            logger.exception(f"Mistral extraction failed: {e}")
            raise GeminiAPIError(
                f"Extraction failed: {str(e)}",
                details={"error_type": "unexpected", "error": str(e)},
            )

    def _build_result(self, data: dict) -> MistralExtractionResult:
        """Build extraction result from parsed JSON.

        Same validation logic as GeminiVisionService._build_result.
        """
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
                continue
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

            dp_packaging_type = item.get("dp_packaging_type")
            valid_packaging = {"blik", "pet", "fles", "doos", "brik", "glas", "zak"}
            if dp_packaging_type and dp_packaging_type.lower() not in valid_packaging:
                dp_packaging_type = None
            elif dp_packaging_type:
                dp_packaging_type = dp_packaging_type.lower()

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
                    dp_expanded_description=dp_expanded_description,
                    dp_pack_quantity=dp_pack_quantity,
                    dp_pack_size=dp_pack_size,
                    dp_pack_unit=dp_pack_unit,
                    dp_packaging_type=dp_packaging_type,
                    dp_product_variant=dp_product_variant,
                    dp_article_code=dp_article_code,
                    dp_is_bio=bool(item.get("dp_is_bio", False)),
                )
            )

        # Parse receipt-level fields
        receipt_time = data.get("receipt_time")
        if receipt_time:
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

        return MistralExtractionResult(
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

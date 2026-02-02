"""
Gemini Vision service for receipt OCR and semantic line item extraction.

Replaces Veryfi for OCR extraction and handles:
- Line item extraction with normalized names
- Belgian pricing conventions (comma→dot, Hoeveelheidsvoordeel)
- Deposit item detection (Leeggoed/Vidange)
- Granular categorization (~200 categories)
- Health scoring
"""

import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

from google import genai
from google.genai import types

from app.core.exceptions import GeminiAPIError
from app.config import get_settings
from app.models.enums import Category
from app.services.categories import GRANULAR_CATEGORIES, get_parent_category

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class ExtractedLineItem:
    """Represents a line item extracted and normalized by Gemini Vision."""

    original_description: str  # Raw OCR text
    normalized_name: str  # Cleaned, semantic name
    quantity: int
    unit_price: Optional[float]
    total_price: float
    is_deposit: bool
    granular_category: str  # Detailed category
    parent_category: Category  # Broad category
    health_score: Optional[int]  # 0-5, None for non-food


@dataclass
class GeminiExtractionResult:
    """Complete extraction result from Gemini Vision."""

    vendor_name: str
    receipt_date: Optional[date]
    total: Optional[float]
    line_items: list[ExtractedLineItem]
    ocr_text: Optional[str]  # Full OCR for debugging


class GeminiVisionService:
    """Gemini Vision integration for receipt OCR and extraction."""

    MODEL = "gemini-3-pro-preview"
    MAX_TOKENS = 8192

    SYSTEM_PROMPT = '''You are a Belgian grocery receipt analyzer. Extract and normalize line items from receipt images.

## EXTRACTION RULES

### Vendor Name
- Clean OCR artifacts, use proper store name
- Common Belgian stores: Colruyt, Delhaize, Carrefour, Aldi, Lidl, Albert Heijn, Spar, Match, Intermarché, Okay, Cora, Makro
- Use title case

### Receipt Date
- Extract the date from the receipt in YYYY-MM-DD format
- Look for "Datum:", "Date:", or date patterns like "02/02/2026" or "02-02-2026"
- Convert DD/MM/YYYY to YYYY-MM-DD

### Line Items - Extract these fields:

1. **original_description**: Raw text exactly as appears on receipt (including codes, quantities, etc.)

2. **normalized_name**: Clean, semantic product name following these rules:
   - REMOVE quantities from name (450ml, 1L, 500g, 10st, 6x33cl, etc.)
   - REMOVE packaging types (PET, Blik, Fles, Doos, Brik, etc.)
   - REMOVE private label markers (Boni, 365, Everyday, Cara, etc.) when they don't define the product
   - KEEP brand names (Coca-Cola, Jupiler, Danone, etc.)
   - Maintain original language (Dutch/French)
   - Use sentence case ("Whole milk" not "WHOLE MILK")
   - Examples:
     - "JUPILER BIER 6X33CL PET" → "Jupiler"
     - "BONI VOLLE MELK 1L" → "Volle melk"
     - "COCA COLA ZERO 1,5L PET" → "Coca-Cola Zero"
     - "VANDEMOORTELE VINAIGRETTE CAESAR 450ML" → "Caesar vinaigrette"
     - "LEFFE BRUIN 6X33CL" → "Leffe Bruin"

3. **quantity**: Number of items (parse from "2x", "x3", "2 ST", etc.). Default to 1.

4. **unit_price**: Price per single item (if shown separately on receipt)

5. **total_price**: Total line price
   - Convert Belgian comma decimals to dots: "2,99" → 2.99
   - Handle "Hoeveelheidsvoordeel" (quantity discount): use the final price shown
   - Handle "Actieprijs" (promotional price): use that price

6. **is_deposit**: True ONLY for deposit items:
   - "Leeggoed" (Dutch)
   - "Vidange" (French)
   - "Statiegeld"
   - These are bottle/can deposits, NOT the actual products

### IMPORTANT RULES
- Skip lines that are purely discounts (negative amounts without a product)
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
Return ONLY valid JSON:
```json
{{
  "vendor_name": "Store Name",
  "receipt_date": "YYYY-MM-DD",
  "total": 45.67,
  "line_items": [
    {{
      "original_description": "JUPILER BIER 6X33CL PET",
      "normalized_name": "Jupiler",
      "quantity": 6,
      "unit_price": 0.89,
      "total_price": 5.34,
      "is_deposit": false,
      "granular_category": "Beer (Pils)",
      "health_score": 0
    }},
    {{
      "original_description": "LEEGGOED 6X",
      "normalized_name": "Leeggoed bier",
      "quantity": 6,
      "unit_price": 0.10,
      "total_price": 0.60,
      "is_deposit": true,
      "granular_category": "Other",
      "health_score": null
    }}
  ],
  "ocr_text": "Full raw OCR text..."
}}
```'''

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("Gemini API key not configured")
        self.client = genai.Client(api_key=self.api_key)

    async def extract_receipt(
        self, file_content: bytes, mime_type: str
    ) -> GeminiExtractionResult:
        """Extract and normalize receipt data using Gemini Vision.

        Uses Gemini's native document processing for PDFs (no conversion needed).
        Supports PDF, JPEG, and PNG files directly.
        """

        # Build prompt with category list
        categories_list = "\n".join(
            f"- {cat}" for cat in GRANULAR_CATEGORIES.keys()
        )
        system_prompt = self.SYSTEM_PROMPT.format(categories=categories_list)

        # Log input details for debugging
        logger.info(f"Gemini extraction: mime_type={mime_type}, content_size={len(file_content)} bytes")

        # Determine the prompt based on file type
        if mime_type == "application/pdf":
            extract_prompt = "Extract all line items from this receipt document. Return JSON only."
        else:
            extract_prompt = "Extract all line items from this receipt image. Return JSON only."

        try:
            # Use types.Part.from_bytes for native PDF/image support
            # This is the recommended method from Gemini API docs for document processing
            response = self.client.models.generate_content(
                model=self.MODEL,
                contents=[
                    types.Part.from_bytes(
                        data=file_content,
                        mime_type=mime_type,
                    ),
                    extract_prompt,
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=self.MAX_TOKENS,
                    temperature=0.1,
                ),
            )

            # Parse response
            response_text = response.text
            json_str = self._extract_json(response_text)
            data = json.loads(json_str)

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

    def _extract_json(self, text: str) -> str:
        """Extract JSON from response, handling markdown code blocks."""
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return text.strip()

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

            line_items.append(
                ExtractedLineItem(
                    original_description=item.get("original_description", ""),
                    normalized_name=item.get("normalized_name", ""),
                    quantity=int(item.get("quantity", 1)),
                    unit_price=unit_price,
                    total_price=total_price,
                    is_deposit=bool(item.get("is_deposit", False)),
                    granular_category=granular,
                    parent_category=parent,
                    health_score=health_score,
                )
            )

        return GeminiExtractionResult(
            vendor_name=data.get("vendor_name", "Unknown"),
            receipt_date=receipt_date,
            total=data.get("total"),
            line_items=line_items,
            ocr_text=data.get("ocr_text"),
        )

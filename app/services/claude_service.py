import base64
import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

import anthropic

from app.core.exceptions import ClaudeAPIError
from app.models.enums import Category
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class ExtractedItem:
    item_name: str
    item_price: float
    quantity: int
    unit_price: Optional[float]
    category: Category
    health_score: Optional[int]  # 0-5, where 0 is unhealthy and 5 is very healthy (None for non-food items)


@dataclass
class ReceiptExtractionResult:
    store_name: str
    receipt_date: Optional[date]
    total_amount: float
    items: List[ExtractedItem]


class ClaudeService:
    """Anthropic Claude Vision API integration for receipt extraction."""

    MODEL = "claude-sonnet-4-20250514"
    MAX_TOKENS = 4096

    SYSTEM_PROMPT = """You are a receipt data extraction assistant. Extract all items from grocery receipts accurately.

For each item, identify:
1. item_name: A clean, readable product name:
   - Extract the actual product name, not codes or gibberish
   - Remove product codes, SKUs, and internal reference numbers
   - Remove weight/quantity info that's captured separately (e.g., "1.5KG", "x2")
   - Keep brand names if visible (e.g., "Coca-Cola", "Danone")
   - Use title case for proper formatting (e.g., "Organic Whole Milk")
2. item_price: The total price for this line item (after quantity multiplication)
3. quantity: Number of units (default 1 if not specified)
4. unit_price: Price per single unit (if different from item_price)
5. category: Classify into exactly one of these categories:
   - "Meat & Fish" (meat, poultry, fish, seafood)
   - "Alcohol" (beer, wine, spirits, including deposit/leeggoed)
   - "Drinks (Soft/Soda)" (sodas, juices, energy drinks)
   - "Drinks (Water)" (water, sparkling water)
   - "Household" (cleaning, paper products, bags)
   - "Snacks & Sweets" (chips, chocolate, candy, cookies)
   - "Fresh Produce" (fruits, vegetables)
   - "Dairy & Eggs" (milk, cheese, yogurt, eggs, butter)
   - "Ready Meals" (prepared foods, salads, soups, pizza, lasagna)
   - "Bakery" (bread, pastries, croissants)
   - "Pantry" (pasta, rice, oil, canned goods, spices, sugar, flour)
   - "Personal Care" (shampoo, soap, dental, deodorant)
   - "Frozen" (frozen foods not in other categories)
   - "Baby & Kids" (diapers, baby food, kids products)
   - "Pet Supplies" (pet food, pet accessories)
   - "Other" (anything that doesn't fit above)
6. health_score: Rate the healthiness of each item from 0 to 5:
   - 5: Very healthy (fresh vegetables, fruits, water, plain nuts)
   - 4: Healthy (whole grains, lean proteins, eggs, plain dairy)
   - 3: Moderately healthy (bread, pasta, cheese, some ready meals)
   - 2: Less healthy (processed meats, sweetened drinks, some snacks)
   - 1: Unhealthy (chips, candy, cookies, sodas, sugary cereals)
   - 0: Very unhealthy (alcohol, energy drinks, heavily processed foods)
   Note: Non-food items (household, personal care, pet supplies) should have health_score: null

Also extract:
- store_name: The clean store name using proper capitalization (e.g., "Colruyt", "Aldi", "Delhaize", "Carrefour", "Lidl")
- receipt_date: Date in ISO format (YYYY-MM-DD)
- total_amount: Total amount paid

IMPORTANT:
- Prices are in EUR
- Belgian receipts may be in Dutch/French
- Handle quantity notations like "2 x 2,79" or "1,782 kg x 1,29 EUR/kg"
- Exclude non-product lines (subtotals, payment info, loyalty points)
- Deposit items (leeggoed/vidange) should be categorized with the related product

Return ONLY valid JSON in this exact format:
{
  "store_name": "STORE",
  "receipt_date": "YYYY-MM-DD",
  "total_amount": 0.00,
  "items": [
    {
      "item_name": "Product Name",
      "item_price": 0.00,
      "quantity": 1,
      "unit_price": 0.00,
      "category": "Category Name",
      "health_score": 3
    }
  ]
}"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        if not self.api_key:
            raise ValueError("Anthropic API key not configured")
        self.client = anthropic.Anthropic(api_key=self.api_key)

    async def extract_receipt_data(
        self, images: List[bytes]
    ) -> ReceiptExtractionResult:
        """
        Extract structured data from receipt image(s) using Claude Vision.
        """
        try:
            # Prepare image content blocks
            content = []
            for img_bytes in images:
                base64_image = base64.standard_b64encode(img_bytes).decode("utf-8")
                media_type = self._detect_media_type(img_bytes)
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64_image,
                        },
                    }
                )

            content.append(
                {
                    "type": "text",
                    "text": "Extract all items from this receipt. Return only the JSON response.",
                }
            )

            # Call Claude API
            response = self.client.messages.create(
                model=self.MODEL,
                max_tokens=self.MAX_TOKENS,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
            )

            # Parse response
            response_text = response.content[0].text

            # Extract JSON from response (handle markdown code blocks)
            json_str = self._extract_json(response_text)
            data = json.loads(json_str)

            # Validate and convert to result object
            return self._parse_extraction_result(data)

        except anthropic.AuthenticationError as e:
            logger.error(f"Claude API authentication failed: {e}. Check your ANTHROPIC_API_KEY.")
            raise ClaudeAPIError(
                "Claude API authentication failed - invalid or missing API key",
                details={"error_type": "authentication", "api_error": str(e)},
            )
        except anthropic.RateLimitError as e:
            logger.warning(f"Claude API rate limit exceeded: {e}")
            raise ClaudeAPIError(
                "Claude API rate limit exceeded - please retry later",
                details={"error_type": "rate_limit", "api_error": str(e)},
            )
        except anthropic.APIStatusError as e:
            logger.error(f"Claude API status error: status={e.status_code}, message={e.message}")
            raise ClaudeAPIError(
                f"Claude API error (status {e.status_code}): {e.message}",
                details={"error_type": "api_status", "status_code": e.status_code, "api_error": str(e)},
            )
        except anthropic.APIConnectionError as e:
            logger.error(f"Claude API connection failed: {e}")
            raise ClaudeAPIError(
                "Failed to connect to Claude API - check network connectivity",
                details={"error_type": "connection", "api_error": str(e)},
            )
        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            raise ClaudeAPIError(
                f"Claude API error: {str(e)}",
                details={"error_type": "api_error", "api_error": str(e)},
            )
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {e}. Response text: {response_text[:500] if 'response_text' in locals() else 'N/A'}")
            raise ClaudeAPIError(
                "Failed to parse Claude response as JSON",
                details={"error_type": "parse_error", "parse_error": str(e)},
            )
        except Exception as e:
            logger.exception(f"Unexpected error during receipt extraction: {e}")
            raise ClaudeAPIError(
                f"Receipt extraction failed: {str(e)}",
                details={"error_type": "unexpected", "error": str(e)},
            )

    def _detect_media_type(self, img_bytes: bytes) -> str:
        """Detect image media type from magic bytes."""
        if img_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"
        elif img_bytes[:2] == b'\xff\xd8':
            return "image/jpeg"
        elif img_bytes[:4] == b'GIF8':
            return "image/gif"
        elif img_bytes[:4] == b'RIFF' and img_bytes[8:12] == b'WEBP':
            return "image/webp"
        # Default to PNG if unknown
        return "image/png"

    def _extract_json(self, text: str) -> str:
        """Extract JSON from response, handling markdown code blocks."""
        # Remove markdown code blocks if present
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return text.strip()

    def _parse_extraction_result(self, data: dict) -> ReceiptExtractionResult:
        """Validate and convert raw JSON to typed result."""
        items = []
        for item_data in data.get("items", []):
            # Validate category
            category_str = item_data.get("category", "Other")
            try:
                category = Category(category_str)
            except ValueError:
                category = Category.OTHER

            # Handle missing or null prices
            item_price = item_data.get("item_price")
            if item_price is None:
                continue  # Skip items without a price

            quantity = int(item_data.get("quantity", 1))
            # Calculate unit_price if not provided by Claude
            unit_price = item_data.get("unit_price")
            if unit_price is None:
                unit_price = item_price / quantity if quantity > 0 else item_price

            # Parse health score (can be null for non-food items)
            health_score_raw = item_data.get("health_score")
            if health_score_raw is not None:
                health_score = max(0, min(5, int(health_score_raw)))  # Clamp to 0-5
            else:
                health_score = None

            items.append(
                ExtractedItem(
                    item_name=item_data.get("item_name", "Unknown Item"),
                    item_price=float(item_price),
                    quantity=quantity,
                    unit_price=float(unit_price),
                    category=category,
                    health_score=health_score,
                )
            )

        # Parse date
        receipt_date = None
        if data.get("receipt_date"):
            try:
                receipt_date = date.fromisoformat(data["receipt_date"])
            except ValueError:
                pass

        return ReceiptExtractionResult(
            store_name=data.get("store_name") or "Unknown",
            receipt_date=receipt_date,
            total_amount=float(data.get("total_amount") or 0),
            items=items,
        )

import base64
import json
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

import anthropic

from app.core.exceptions import ClaudeAPIError
from app.models.enums import Category
from app.config import get_settings

settings = get_settings()


@dataclass
class ExtractedItem:
    item_name: str
    item_price: float
    quantity: int
    unit_price: Optional[float]
    category: Category


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
1. item_name: The product name as shown on receipt
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

Also extract:
- store_name: The store name (e.g., "COLRUYT", "ALDI")
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
      "category": "Category Name"
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
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
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

        except anthropic.APIError as e:
            raise ClaudeAPIError(
                f"Claude API error: {str(e)}",
                details={"api_error": str(e)},
            )
        except json.JSONDecodeError as e:
            raise ClaudeAPIError(
                "Failed to parse Claude response as JSON",
                details={"parse_error": str(e)},
            )
        except Exception as e:
            raise ClaudeAPIError(
                f"Receipt extraction failed: {str(e)}",
                details={"error": str(e)},
            )

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

            items.append(
                ExtractedItem(
                    item_name=item_data["item_name"],
                    item_price=float(item_data["item_price"]),
                    quantity=int(item_data.get("quantity", 1)),
                    unit_price=float(item_data.get("unit_price") or item_data["item_price"]),
                    category=category,
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
            store_name=data.get("store_name", "Unknown"),
            receipt_date=receipt_date,
            total_amount=float(data.get("total_amount", 0)),
            items=items,
        )

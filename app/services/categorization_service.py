import json
import logging
from dataclasses import dataclass
from typing import List, Optional

import anthropic

from app.core.exceptions import ClaudeAPIError
from app.models.enums import Category
from app.config import get_settings
from app.services.veryfi_service import VeryfiLineItem

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class CategorizedItem:
    """Represents a categorized item with health score."""
    item_name: str
    item_price: float
    quantity: int
    unit_price: Optional[float]
    category: Category
    health_score: Optional[int]  # 0-5, None for non-food items


class CategorizationService:
    """Anthropic Claude integration for categorizing items and assigning health scores."""

    MODEL = "claude-sonnet-4-20250514"
    MAX_TOKENS = 4096

    SYSTEM_PROMPT = """You are a grocery item categorization assistant. Given a list of items from a receipt, categorize each item and assign a health score.

For each item, provide:
1. category: Classify into exactly one of these categories:
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

2. health_score: Rate the healthiness of each item from 0 to 5:
   - 5: Very healthy (fresh vegetables, fruits, water, plain nuts)
   - 4: Healthy (whole grains, lean proteins, eggs, plain dairy)
   - 3: Moderately healthy (bread, pasta, cheese, some ready meals)
   - 2: Less healthy (processed meats, sweetened drinks, some snacks)
   - 1: Unhealthy (chips, candy, cookies, sodas, sugary cereals)
   - 0: Very unhealthy (alcohol, energy drinks, heavily processed foods)
   Note: Non-food items (household, personal care, pet supplies) should have health_score: null

IMPORTANT:
- Belgian receipts may have Dutch/French product names
- Deposit items (leeggoed/vidange) should be categorized with the related product (usually Alcohol or Drinks)
- Use the item type hint if provided (e.g., "food", "alcohol", "product")

Return ONLY valid JSON as an array with this exact format:
[
  {
    "index": 0,
    "category": "Category Name",
    "health_score": 3
  }
]

The "index" must match the position of the item in the input list (0-indexed)."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        if not self.api_key:
            raise ValueError("Anthropic API key not configured")
        self.client = anthropic.Anthropic(api_key=self.api_key)

    async def categorize_items(
        self, items: List[VeryfiLineItem]
    ) -> List[CategorizedItem]:
        """
        Categorize items and assign health scores using Claude.

        Args:
            items: List of VeryfiLineItem from OCR extraction

        Returns:
            List of CategorizedItem with categories and health scores
        """
        if not items:
            return []

        try:
            # Prepare items for categorization
            items_text = self._format_items_for_prompt(items)

            # Call Claude API
            response = self.client.messages.create(
                model=self.MODEL,
                max_tokens=self.MAX_TOKENS,
                system=self.SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": f"Categorize these items from a receipt:\n\n{items_text}",
                    }
                ],
            )

            # Parse response
            response_text = response.content[0].text
            json_str = self._extract_json(response_text)
            categorizations = json.loads(json_str)

            # Build result combining Veryfi data with Claude categorizations
            return self._build_categorized_items(items, categorizations)

        except anthropic.AuthenticationError as e:
            logger.error(f"Claude API authentication failed: {e}")
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
            logger.error(f"Failed to parse Claude response as JSON: {e}")
            raise ClaudeAPIError(
                "Failed to parse Claude response as JSON",
                details={"error_type": "parse_error", "parse_error": str(e)},
            )
        except Exception as e:
            logger.exception(f"Unexpected error during categorization: {e}")
            raise ClaudeAPIError(
                f"Categorization failed: {str(e)}",
                details={"error_type": "unexpected", "error": str(e)},
            )

    def _format_items_for_prompt(self, items: List[VeryfiLineItem]) -> str:
        """Format items as text for the Claude prompt."""
        lines = []
        for i, item in enumerate(items):
            type_hint = f" (type: {item.type})" if item.type else ""
            lines.append(f"{i}. {item.description}{type_hint}")
        return "\n".join(lines)

    def _extract_json(self, text: str) -> str:
        """Extract JSON from response, handling markdown code blocks."""
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return text.strip()

    def _build_categorized_items(
        self,
        items: List[VeryfiLineItem],
        categorizations: List[dict],
    ) -> List[CategorizedItem]:
        """Build CategorizedItem list by combining Veryfi data with Claude categorizations."""
        # Create a lookup for categorizations by index
        cat_lookup = {cat.get("index", i): cat for i, cat in enumerate(categorizations)}

        result = []
        for i, item in enumerate(items):
            # Skip items without a price
            if item.total is None and item.price is None:
                continue

            # Get categorization from Claude response
            cat_data = cat_lookup.get(i, {})

            # Parse category
            category_str = cat_data.get("category", "Other")
            try:
                category = Category(category_str)
            except ValueError:
                category = Category.OTHER

            # Parse health score
            health_score_raw = cat_data.get("health_score")
            if health_score_raw is not None:
                health_score = max(0, min(5, int(health_score_raw)))
            else:
                health_score = None

            # Calculate prices
            total_price = item.total if item.total is not None else item.price
            quantity = int(item.quantity) if item.quantity else 1
            unit_price = item.price if item.price else (total_price / quantity if quantity > 0 else total_price)

            result.append(
                CategorizedItem(
                    item_name=item.description,
                    item_price=float(total_price),
                    quantity=quantity,
                    unit_price=float(unit_price) if unit_price else None,
                    category=category,
                    health_score=health_score,
                )
            )

        return result

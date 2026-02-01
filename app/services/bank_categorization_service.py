import json
import logging
from dataclasses import dataclass
from typing import Optional, List

from google import genai
from google.genai import types

from app.core.exceptions import GeminiAPIError
from app.models.enums import Category
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class CategorySuggestion:
    """Suggested category for a bank transaction."""

    category: Category
    confidence: float  # 0.0 to 1.0
    reasoning: Optional[str] = None


@dataclass
class BulkCategorySuggestion:
    """Category suggestion for a transaction in bulk processing."""

    transaction_index: int
    category: Category
    confidence: float
    store_name: Optional[str] = None  # Cleaned merchant name


class BankCategorizationService:
    """Service for suggesting categories for bank transactions using Gemini AI."""

    MODEL = "gemini-2.0-flash"
    MAX_TOKENS = 2048

    SYSTEM_PROMPT = """You are a financial transaction categorization assistant. Given bank transaction details (merchant name and description), categorize each transaction into the appropriate spending category.

Available categories:
- "Meat & Fish" (butcher shops, fish markets)
- "Alcohol" (liquor stores, bars, pubs)
- "Drinks (Soft/Soda)" (beverage shops)
- "Drinks (Water)" (water delivery)
- "Household" (home goods, hardware, furniture)
- "Snacks & Sweets" (candy shops, bakeries selling treats)
- "Fresh Produce" (farmers markets, greengrocers)
- "Dairy & Eggs" (dairy shops)
- "Ready Meals" (restaurants, fast food, takeaway, meal delivery like Deliveroo/UberEats)
- "Bakery" (bakeries, bread shops)
- "Pantry" (grocery stores, supermarkets - use this for general grocery shopping)
- "Personal Care" (pharmacies, beauty shops, hairdressers, gyms)
- "Frozen" (ice cream shops, frozen food stores)
- "Baby & Kids" (toy stores, children's clothing, baby supplies)
- "Pet Supplies" (pet shops, veterinarians)
- "Tobacco" (tobacco shops)
- "Other" (anything that doesn't fit above - use for non-grocery expenses like utilities, subscriptions, etc.)

For each transaction, provide:
1. category: The most appropriate category from the list above
2. confidence: Your confidence level (0.0-1.0) based on how clear the categorization is
3. store_name: A cleaned, readable version of the merchant name (proper case, remove garbage characters)

Common merchant patterns:
- Supermarkets (Colruyt, Delhaize, Carrefour, Aldi, Lidl, Albert Heijn) → "Pantry"
- Restaurants, cafes, fast food → "Ready Meals"
- Pharmacies (Apotheek, Pharmacie) → "Personal Care"
- Gas stations often have convenience stores → "Pantry" or "Other" depending on context

Return ONLY valid JSON in this exact format:
{
  "suggestions": [
    {
      "index": 0,
      "category": "Category Name",
      "confidence": 0.85,
      "store_name": "Clean Merchant Name"
    }
  ]
}"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("Gemini API key not configured")
        self.client = genai.Client(api_key=self.api_key)

    async def suggest_category(
        self,
        merchant_name: Optional[str],
        description: Optional[str] = None,
    ) -> CategorySuggestion:
        """
        Suggest a category for a single bank transaction.

        Args:
            merchant_name: The merchant/creditor/debtor name from the transaction
            description: Additional transaction description or remittance info

        Returns:
            CategorySuggestion with suggested category and confidence
        """
        if not merchant_name and not description:
            return CategorySuggestion(
                category=Category.OTHER,
                confidence=0.0,
                reasoning="No merchant name or description provided",
            )

        try:
            # Build prompt
            info_parts = []
            if merchant_name:
                info_parts.append(f"Merchant: {merchant_name}")
            if description:
                info_parts.append(f"Description: {description}")

            user_content = "\n".join(info_parts)

            # Call Gemini API
            response = self.client.models.generate_content(
                model=self.MODEL,
                contents=f"Categorize this transaction:\n\n{user_content}",
                config=types.GenerateContentConfig(
                    system_instruction=self.SYSTEM_PROMPT,
                    max_output_tokens=512,
                    temperature=0.1,
                ),
            )

            # Parse response
            response_text = response.text
            json_str = self._extract_json(response_text)
            result_data = json.loads(json_str)

            suggestions = result_data.get("suggestions", [])
            if not suggestions:
                return CategorySuggestion(
                    category=Category.OTHER,
                    confidence=0.5,
                    reasoning="No suggestion returned",
                )

            suggestion = suggestions[0]
            category_str = suggestion.get("category", "Other")
            try:
                category = Category(category_str)
            except ValueError:
                category = Category.OTHER

            confidence = float(suggestion.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))

            return CategorySuggestion(
                category=category,
                confidence=confidence,
                reasoning=suggestion.get("store_name"),
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response: {e}")
            return CategorySuggestion(
                category=Category.OTHER,
                confidence=0.0,
                reasoning="Failed to parse AI response",
            )
        except Exception as e:
            logger.exception(f"Error during category suggestion: {e}")
            return CategorySuggestion(
                category=Category.OTHER,
                confidence=0.0,
                reasoning=str(e),
            )

    async def suggest_categories_bulk(
        self,
        transactions: List[dict],
    ) -> List[BulkCategorySuggestion]:
        """
        Suggest categories for multiple bank transactions in a single API call.

        Args:
            transactions: List of dicts with 'merchant_name' and 'description' keys

        Returns:
            List of BulkCategorySuggestion for each transaction
        """
        if not transactions:
            return []

        try:
            # Format transactions for prompt
            lines = []
            for i, txn in enumerate(transactions):
                merchant = txn.get("merchant_name", "Unknown")
                desc = txn.get("description", "")
                line = f"{i}. Merchant: {merchant}"
                if desc:
                    line += f" | Description: {desc}"
                lines.append(line)

            user_content = "\n".join(lines)

            # Call Gemini API
            response = self.client.models.generate_content(
                model=self.MODEL,
                contents=f"Categorize these {len(transactions)} transactions:\n\n{user_content}",
                config=types.GenerateContentConfig(
                    system_instruction=self.SYSTEM_PROMPT,
                    max_output_tokens=self.MAX_TOKENS,
                    temperature=0.1,
                ),
            )

            # Parse response
            response_text = response.text
            json_str = self._extract_json(response_text)
            result_data = json.loads(json_str)

            suggestions = result_data.get("suggestions", [])

            # Build result list
            results = []
            suggestions_by_index = {s.get("index", i): s for i, s in enumerate(suggestions)}

            for i in range(len(transactions)):
                suggestion = suggestions_by_index.get(i, {})

                category_str = suggestion.get("category", "Other")
                try:
                    category = Category(category_str)
                except ValueError:
                    category = Category.OTHER

                confidence = float(suggestion.get("confidence", 0.5))
                confidence = max(0.0, min(1.0, confidence))

                results.append(
                    BulkCategorySuggestion(
                        transaction_index=i,
                        category=category,
                        confidence=confidence,
                        store_name=suggestion.get("store_name"),
                    )
                )

            return results

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini bulk response: {e}")
            raise GeminiAPIError(
                "Failed to parse Gemini response",
                details={"error_type": "parse_error", "error": str(e)},
            )
        except Exception as e:
            logger.exception(f"Error during bulk category suggestion: {e}")
            raise GeminiAPIError(
                f"Bulk categorization failed: {str(e)}",
                details={"error_type": "unexpected", "error": str(e)},
            )

    def _extract_json(self, text: str) -> str:
        """Extract JSON from response, handling markdown code blocks."""
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return text.strip()

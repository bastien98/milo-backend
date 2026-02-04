import json
from dataclasses import dataclass
from typing import List, Optional

from google import genai
from google.genai import types

from app.core.exceptions import GeminiAPIError
from app.services.category_registry import get_category_registry
from app.config import get_settings
from app.services.veryfi_service import VeryfiLineItem

settings = get_settings()


@dataclass
class CategorizedItem:
    """Represents a categorized item with health score."""
    item_name: str
    item_price: float
    quantity: int
    unit_price: Optional[float]
    category: str
    health_score: Optional[int]  # 0-5, None for non-food items


@dataclass
class CategorizationResult:
    """Result of categorization including cleaned store name and items."""
    store_name: Optional[str]
    items: List[CategorizedItem]


class CategorizationServiceGemini:
    """Google Gemini integration for categorizing items and assigning health scores."""

    MODEL = "gemini-2.0-flash"
    MAX_TOKENS = 4096

    SYSTEM_PROMPT = """You are a receipt and transaction categorization assistant. Given a store name and list of items from a receipt (grocery, restaurant, utility bill, service receipt, etc.), clean up the data, categorize each item into one of the sub-categories below, assign a health score where applicable, and DEDUPLICATE items.

IMPORTANT - MULTI-SECTION RECEIPT HANDLING:
Receipt images may consist of multiple overlapping sections captured from a long receipt. This means the SAME LINE ITEM may appear multiple times in the input list due to overlap between sections. You MUST identify and merge these duplicates:
- Look for items with the same or very similar product names (accounting for OCR variations)
- Items with identical or nearly identical prices are likely duplicates from overlapping sections
- When you find duplicates, merge them into a SINGLE entry and list all original indices in "original_indices"
- DO NOT sum quantities/prices for duplicates - they represent the SAME purchase captured multiple times
- Only sum quantities when items are genuinely purchased multiple times (e.g., "2x Milk" on the receipt)

First, clean the store name:
- Remove garbage characters, random symbols, and OCR artifacts
- Fix obvious OCR errors and misspellings
- Use the proper/official store name (e.g., "COLRUYT" -> "Colruyt", "C0LRUYT LAAGSTE" -> "Colruyt")
- Use title case for proper formatting
- Common Belgian stores: Colruyt, Delhaize, Carrefour, Aldi, Lidl, Albert Heijn, Spar, Match, Intermarche

For each UNIQUE item (after deduplication), provide:

1. item_name: Clean up the raw OCR text to produce a clear, readable product name:
   - Remove garbage characters, random symbols, and OCR artifacts
   - Remove product codes, SKUs, and internal reference numbers
   - Remove weight/quantity info that's already captured separately (e.g., "1.5KG", "x2")
   - Fix obvious OCR errors and misspellings
   - Keep the actual product name clear and concise
   - Keep brand names if recognizable (e.g., "Coca-Cola", "Danone")
   - Use title case for proper formatting

2. category: Classify into EXACTLY one of these sub-categories (use the exact string):

   HOUSING & UTILITIES:
   - "Rent Payment"
   - "Mortgage Principal & Interest"
   - "Property Tax"
   - "HOA / Syndic Fees"
   - "Electricity"
   - "Water & Sewer"
   - "Natural Gas / Heating Oil"
   - "Trash & Recycling"
   - "Internet / Wi-Fi"
   - "Cable / Satellite TV"
   - "Mobile Phone Plan"
   - "Home Phone / Landline"
   - "Home Security Service"
   - "Repairs (Plumbing/HVAC)"
   - "Lawn Care / Gardening"
   - "Cleaning Services"
   - "Furniture & Decor"
   - "Home Improvement Supplies"

   FOOD & DINING:
   - "Fresh Produce (Fruit & Veg)" (fruits, vegetables)
   - "Meat Poultry & Seafood" (meat, poultry, fish, seafood)
   - "Dairy Cheese & Eggs" (milk, cheese, yogurt, eggs, butter)
   - "Bakery & Bread" (bread, pastries, croissants)
   - "Pantry Staples (Pasta/Rice/Oil)" (pasta, rice, oil, canned goods, spices, sugar, flour)
   - "Frozen Foods" (frozen foods)
   - "Snacks & Candy" (chips, chocolate, candy, cookies)
   - "Beverages (Non-Alcoholic)" (sodas, juices, energy drinks, water)
   - "Baby Food & Formula"
   - "Pet Food & Supplies" (pet food, pet accessories)
   - "Household Consumables (Paper/Cleaning)" (cleaning products, paper towels, bags)
   - "Personal Hygiene (Soap/Shampoo)" (shampoo, soap, dental, deodorant)
   - "Ready Meals & Prepared Food" (prepared foods, salads, soups, pizza, lasagna)
   - "Tobacco Products" (cigarettes, rolling tobacco, lighters, rolling papers, filters, e-cigarettes, vapes)
   - "Fast Food / Quick Service"
   - "Sit-down Restaurants"
   - "Coffee Shops & Cafes"
   - "Bars & Nightlife"
   - "Food Delivery (Apps)" (Deliveroo, UberEats, etc.)
   - "Liquor Store / Wine Shop" (spirits, wine from a liquor store)
   - "Beer & Wine (Retail)" (beer and wine bought at a retail/grocery store, including deposit/leeggoed)

   TRANSPORTATION:
   - "Car Payment (Loan/Lease)"
   - "Auto Insurance"
   - "Registration & Inspection Fees"
   - "Fuel (Gas/Diesel/Electric)"
   - "Maintenance & Oil Changes"
   - "Repairs & Parts"
   - "Car Wash & Detailing"
   - "Ride Share (Uber/Lyft)"
   - "Public Transit (Bus/Train)"
   - "Taxi Services"
   - "Parking Fees & Tolls"
   - "Bike/Scooter Rentals"

   HEALTH & WELLNESS:
   - "Primary Care / Doctor Visits"
   - "Specialist Visits"
   - "Dental Care"
   - "Vision / Optometry"
   - "Pharmacy & Prescriptions"
   - "Health Insurance Premiums"
   - "Life Insurance"
   - "Disability Insurance"
   - "Gym Memberships"
   - "Sports Equipment"
   - "Vitamins & Supplements"
   - "Therapy / Counseling"

   SHOPPING & PERSONAL CARE:
   - "Apparel (Adults)"
   - "Apparel (Kids)"
   - "Shoes & Footwear"
   - "Jewelry & Watches"
   - "Dry Cleaning & Tailoring"
   - "Computers & Tablets"
   - "Phones & Accessories"
   - "Software Subscriptions"
   - "Gaming & Consoles"
   - "Hair Salon / Barbershop"
   - "Spa & Massage"
   - "Cosmetics & Makeup"
   - "Nail Salon"

   ENTERTAINMENT & LEISURE:
   - "Streaming Video (Netflix/Hulu)"
   - "Streaming Audio (Spotify/Music)"
   - "News & Magazines"
   - "Movies & Theaters"
   - "Concerts & Festivals"
   - "Sporting Events"
   - "Museums & Exhibitions"
   - "Arts & Crafts"
   - "Books & Audiobooks"
   - "Musical Instruments"
   - "Photography"

   FINANCIAL & LEGAL:
   - "Emergency Fund Transfer"
   - "Retirement (Pension/401k)"
   - "Investments / Brokerage"
   - "Crypto Purchases"
   - "Credit Card Payments"
   - "Student Loan Payments"
   - "Personal Loan Payments"
   - "Bank Fees (Overdraft/ATM)"
   - "Credit Card Interest"
   - "Income Tax Payments"
   - "Tax Prep Services"
   - "Legal Fees"

   FAMILY & EDUCATION:
   - "Tuition & Fees"
   - "Student Loan Interest"
   - "Textbooks & Supplies"
   - "Online Courses"
   - "Daycare / Babysitting"
   - "Toys & Games"
   - "Baby Supplies (Diapers)"
   - "Extracurriculars"
   - "Veterinary Bills"
   - "Pet Grooming"
   - "Pet Sitting / Boarding"

   TRAVEL & VACATION:
   - "Airfare"
   - "Train/Bus (Long Distance)"
   - "Car Rental"
   - "Cruise Tickets"
   - "Hotels & Resorts"
   - "Airbnb / Vacation Rentals"
   - "Vacation Dining"
   - "Sightseeing & Tours"
   - "Souvenirs"
   - "Travel Insurance"

   GIFTS & DONATIONS:
   - "Birthday Gifts"
   - "Holiday Gifts"
   - "Wedding/Party Gifts"
   - "Charitable Donations"
   - "Religious Tithing"
   - "Political Contributions"

   MISCELLANEOUS:
   - "Cash Withdrawals"
   - "Reimbursements (Pending)"
   - "Adjustment / Correction"
   - "Unknown Transaction"

3. health_score: ONLY for items in the FOOD & DINING group, rate healthiness from 0 to 5:
   - 5: Very healthy (fresh vegetables, fruits, water, plain nuts)
   - 4: Healthy (whole grains, lean proteins, eggs, plain dairy)
   - 3: Moderately healthy (bread, pasta, cheese, some ready meals)
   - 2: Less healthy (processed meats, sweetened drinks, some snacks)
   - 1: Unhealthy (chips, candy, cookies, sodas, sugary cereals)
   - 0: Very unhealthy (alcohol, energy drinks, heavily processed foods)
   For ALL items NOT in Food & Dining group, set health_score: null

4. original_indices: List of indices from the input that correspond to this item.
   - For unique items: single index, e.g., [0]
   - For duplicates found in overlapping sections: all indices, e.g., [2, 7, 12]

IMPORTANT:
- Belgian receipts may have Dutch/French product names - keep in the original language but clean up the text
- Deposit items (leeggoed/vidange) should be categorized with the related product (usually "Beer & Wine (Retail)" or "Beverages (Non-Alcoholic)")
- Use the item type hint if provided (e.g., "food", "alcohol", "product")
- The number of items in output should be LESS than or EQUAL to input if duplicates were found
- You MUST use the EXACT sub-category string from the list above (e.g., "Fresh Produce (Fruit & Veg)" not "Fresh Produce")

Return ONLY valid JSON with this exact format:
{
  "store_name": "Clean Store Name",
  "items": [
    {
      "original_indices": [0],
      "item_name": "Clean Product Name",
      "category": "Fresh Produce (Fruit & Veg)",
      "health_score": 5
    },
    {
      "original_indices": [1, 5, 9],
      "item_name": "Merged Duplicate Product",
      "category": "Dairy Cheese & Eggs",
      "health_score": 4
    }
  ]
}"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("Gemini API key not configured")
        self.client = genai.Client(api_key=self.api_key)

    async def categorize_items(
        self, items: List[VeryfiLineItem], vendor_name: Optional[str] = None
    ) -> CategorizationResult:
        """
        Categorize items and assign health scores using Gemini.

        Args:
            items: List of VeryfiLineItem from OCR extraction
            vendor_name: Raw vendor/store name from OCR to be cleaned

        Returns:
            CategorizationResult with cleaned store name and categorized items
        """
        if not items:
            return CategorizationResult(store_name=vendor_name, items=[])

        try:
            # Prepare items for categorization
            items_text = self._format_items_for_prompt(items)

            # Build user message with store name
            store_line = f"Store name: {vendor_name}\n\n" if vendor_name else "Store name: Unknown\n\n"
            user_content = f"{store_line}Items:\n{items_text}"

            # Call Gemini API
            response = self.client.models.generate_content(
                model=self.MODEL,
                contents=f"Clean and categorize this receipt data:\n\n{user_content}",
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

            # Extract cleaned store name and items from response
            cleaned_store_name = result_data.get("store_name") or vendor_name
            categorizations = result_data.get("items", [])

            # Build result combining Veryfi data with Gemini categorizations
            categorized_items = self._build_categorized_items(items, categorizations)
            return CategorizationResult(store_name=cleaned_store_name, items=categorized_items)

        except json.JSONDecodeError as e:
            raise GeminiAPIError(
                "Failed to parse Gemini response as JSON",
                details={"error_type": "parse_error", "parse_error": str(e)},
            )
        except Exception as e:
            raise GeminiAPIError(
                f"Categorization failed: {str(e)}",
                details={"error_type": "unexpected", "error": str(e)},
            )

    def _format_items_for_prompt(self, items: List[VeryfiLineItem]) -> str:
        """Format items as text for the Gemini prompt."""
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
        """Build CategorizedItem list by combining Veryfi data with Gemini categorizations.

        Handles deduplicated items where Gemini has merged duplicates from overlapping
        receipt sections. Uses 'original_indices' to map back to Veryfi data.
        """
        result = []

        for cat_data in categorizations:
            # Get the original indices - supports both new format (original_indices)
            # and legacy format (index) for backward compatibility
            original_indices = cat_data.get("original_indices")
            if original_indices is None:
                # Fallback to legacy single index format
                legacy_index = cat_data.get("index")
                if legacy_index is not None:
                    original_indices = [legacy_index]
                else:
                    continue

            if not original_indices:
                continue

            # Use the first index as the primary source for price/quantity data
            primary_index = original_indices[0]
            if primary_index >= len(items):
                continue

            primary_item = items[primary_index]

            # Skip items without a price
            if primary_item.total is None and primary_item.price is None:
                continue

            # Parse category with registry validation
            category_str = cat_data.get("category", "Unknown Transaction")
            registry = get_category_registry()
            if not registry.is_valid(category_str):
                # Try fuzzy matching
                matched = registry.find_closest_match(category_str)
                category_str = matched if matched else "Unknown Transaction"

            # Parse health score
            health_score_raw = cat_data.get("health_score")
            if health_score_raw is not None:
                health_score = max(0, min(5, int(health_score_raw)))
            else:
                health_score = None

            # Get cleaned item name from Gemini, fallback to raw description
            cleaned_name = cat_data.get("item_name") or primary_item.description

            # Calculate prices from primary item (not summing duplicates)
            total_price = primary_item.total if primary_item.total is not None else primary_item.price
            quantity = int(primary_item.quantity) if primary_item.quantity else 1
            unit_price = primary_item.price if primary_item.price else (total_price / quantity if quantity > 0 else total_price)

            result.append(
                CategorizedItem(
                    item_name=cleaned_name,
                    item_price=float(total_price),
                    quantity=quantity,
                    unit_price=float(unit_price) if unit_price else None,
                    category=category_str,
                    health_score=health_score,
                )
            )

        return result

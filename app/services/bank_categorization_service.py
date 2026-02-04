import json
from dataclasses import dataclass
from typing import Optional, List

from google import genai
from google.genai import types

from app.core.exceptions import GeminiAPIError
from app.services.category_registry import get_category_registry
from app.config import get_settings

settings = get_settings()


@dataclass
class CategorySuggestion:
    """Suggested category for a bank transaction."""

    category: str
    confidence: float  # 0.0 to 1.0
    reasoning: Optional[str] = None


@dataclass
class BulkCategorySuggestion:
    """Category suggestion for a transaction in bulk processing."""

    transaction_index: int
    category: str
    confidence: float
    store_name: Optional[str] = None  # Cleaned merchant name


class BankCategorizationService:
    """Service for suggesting categories for bank transactions using Gemini AI."""

    MODEL = "gemini-2.0-flash"
    MAX_TOKENS = 2048

    SYSTEM_PROMPT = """You are a financial transaction categorization assistant. Given bank transaction details (merchant name, IBAN transfer info, and/or description), categorize each transaction into the most appropriate sub-category from the list below.

You MUST use the EXACT sub-category string from the list. Do not invent new categories.

AVAILABLE SUB-CATEGORIES (organized by group):

HOUSING & UTILITIES:
- "Rent Payment" (rent transfers, landlord payments)
- "Mortgage Principal & Interest" (mortgage payments)
- "Property Tax" (property/real estate tax)
- "HOA / Syndic Fees" (building management, syndic)
- "Electricity" (electric utility bills)
- "Water & Sewer" (water utility bills)
- "Natural Gas / Heating Oil" (gas/heating bills)
- "Trash & Recycling" (waste collection)
- "Internet / Wi-Fi" (ISP payments: Proximus, Telenet, VOO, Orange)
- "Cable / Satellite TV" (TV subscriptions)
- "Mobile Phone Plan" (mobile carrier bills)
- "Home Phone / Landline" (landline bills)
- "Home Security Service" (alarm/security systems)
- "Repairs (Plumbing/HVAC)" (home repair services)
- "Lawn Care / Gardening" (garden maintenance)
- "Cleaning Services" (house cleaning)
- "Furniture & Decor" (IKEA, furniture stores)
- "Home Improvement Supplies" (Brico, Gamma, hardware stores)

FOOD & DINING:
- "Fresh Produce (Fruit & Veg)" (farmers markets, greengrocers)
- "Meat Poultry & Seafood" (butcher shops, fish markets)
- "Dairy Cheese & Eggs" (dairy shops, fromageries)
- "Bakery & Bread" (bakeries, bread shops)
- "Pantry Staples (Pasta/Rice/Oil)" (general grocery/supermarket purchases: Colruyt, Delhaize, Carrefour, Aldi, Lidl, Albert Heijn, Spar, Match)
- "Frozen Foods" (frozen food stores)
- "Snacks & Candy" (candy shops, snack stores)
- "Beverages (Non-Alcoholic)" (beverage shops, water delivery)
- "Baby Food & Formula" (baby food stores)
- "Pet Food & Supplies" (pet shops)
- "Household Consumables (Paper/Cleaning)" (cleaning product stores)
- "Personal Hygiene (Soap/Shampoo)" (Kruidvat, Di, drugstores)
- "Ready Meals & Prepared Food" (prepared food shops, traiteurs)
- "Tobacco Products" (tabac shops)
- "Fast Food / Quick Service" (McDonald's, Quick, Burger King, kebab shops)
- "Sit-down Restaurants" (restaurants, brasseries)
- "Coffee Shops & Cafes" (Starbucks, cafes, tea rooms)
- "Bars & Nightlife" (bars, pubs, clubs)
- "Food Delivery (Apps)" (Deliveroo, UberEats, Takeaway.com)
- "Liquor Store / Wine Shop" (wine merchants, spirits shops)
- "Beer & Wine (Retail)" (beer/wine at retail)

TRANSPORTATION:
- "Car Payment (Loan/Lease)" (auto financing, leasing)
- "Auto Insurance" (car insurance: AG, Ethias, AXA)
- "Registration & Inspection Fees" (DIV, vehicle registration)
- "Fuel (Gas/Diesel/Electric)" (gas stations: TotalEnergies, Shell, Q8, Lukoil)
- "Maintenance & Oil Changes" (garage, car servicing)
- "Repairs & Parts" (auto parts, repair shops)
- "Car Wash & Detailing" (car wash)
- "Ride Share (Uber/Lyft)" (Uber, Bolt, Lyft)
- "Public Transit (Bus/Train)" (SNCB/NMBS, STIB/MIVB, De Lijn, TEC)
- "Taxi Services" (taxi companies)
- "Parking Fees & Tolls" (parking meters, garages, highway tolls)
- "Bike/Scooter Rentals" (Villo, scooter sharing)

HEALTH & WELLNESS:
- "Primary Care / Doctor Visits" (GP, doctor visits, mutualite/mutualiteit)
- "Specialist Visits" (specialist doctors)
- "Dental Care" (dentist)
- "Vision / Optometry" (optician, eye care)
- "Pharmacy & Prescriptions" (pharmacies/apotheek)
- "Health Insurance Premiums" (mutuelle, health insurance)
- "Life Insurance" (life insurance)
- "Disability Insurance" (disability coverage)
- "Gym Memberships" (Basic Fit, Jims, fitness clubs)
- "Sports Equipment" (Decathlon, sports stores)
- "Vitamins & Supplements" (supplement shops)
- "Therapy / Counseling" (psychologist, therapist)

SHOPPING & PERSONAL CARE:
- "Apparel (Adults)" (H&M, Zara, Primark, clothing stores)
- "Apparel (Kids)" (children's clothing)
- "Shoes & Footwear" (shoe stores)
- "Jewelry & Watches" (jewelers)
- "Dry Cleaning & Tailoring" (pressing, dry cleaners)
- "Computers & Tablets" (MediaMarkt, Coolblue, electronics)
- "Phones & Accessories" (phone shops)
- "Software Subscriptions" (SaaS, app subscriptions)
- "Gaming & Consoles" (game stores, gaming subscriptions)
- "Hair Salon / Barbershop" (hairdresser, kapper)
- "Spa & Massage" (wellness, spa)
- "Cosmetics & Makeup" (beauty stores, Sephora, ICI Paris)
- "Nail Salon" (nail care)

ENTERTAINMENT & LEISURE:
- "Streaming Video (Netflix/Hulu)" (Netflix, Disney+, Amazon Prime Video)
- "Streaming Audio (Spotify/Music)" (Spotify, Apple Music, Deezer)
- "News & Magazines" (newspaper/magazine subscriptions)
- "Movies & Theaters" (Kinepolis, UGC, cinema)
- "Concerts & Festivals" (Ticketmaster, concert venues)
- "Sporting Events" (sports tickets)
- "Museums & Exhibitions" (museums, exhibitions)
- "Arts & Crafts" (hobby/craft stores)
- "Books & Audiobooks" (Standaard Boekhandel, bookstores, Audible)
- "Musical Instruments" (music stores)
- "Photography" (photo equipment, printing)

FINANCIAL & LEGAL:
- "Emergency Fund Transfer" (savings transfers)
- "Retirement (Pension/401k)" (pension contributions)
- "Investments / Brokerage" (investment platforms, Bolero, DeGiro)
- "Crypto Purchases" (crypto exchanges, Coinbase, Binance)
- "Credit Card Payments" (credit card bill payments)
- "Student Loan Payments" (student loan)
- "Personal Loan Payments" (personal loan)
- "Bank Fees (Overdraft/ATM)" (bank charges, ATM fees)
- "Credit Card Interest" (interest charges)
- "Income Tax Payments" (tax payments, FOD Financien)
- "Tax Prep Services" (accountant, tax advisor)
- "Legal Fees" (lawyer, notary/notaris)

FAMILY & EDUCATION:
- "Tuition & Fees" (school fees, university)
- "Student Loan Interest" (student loan interest)
- "Textbooks & Supplies" (school supplies)
- "Online Courses" (Udemy, Coursera, online learning)
- "Daycare / Babysitting" (creche, childcare)
- "Toys & Games" (toy stores, Dreamland)
- "Baby Supplies (Diapers)" (baby stores)
- "Extracurriculars" (sports clubs, music lessons for kids)
- "Veterinary Bills" (vet, dierenarts)
- "Pet Grooming" (pet grooming)
- "Pet Sitting / Boarding" (pet boarding, pet sitting)

TRAVEL & VACATION:
- "Airfare" (airlines: Brussels Airlines, Ryanair, TUI fly)
- "Train/Bus (Long Distance)" (Thalys, Eurostar, FlixBus)
- "Car Rental" (Europcar, Hertz, Avis)
- "Cruise Tickets" (cruise bookings)
- "Hotels & Resorts" (Booking.com, hotels)
- "Airbnb / Vacation Rentals" (Airbnb, vacation rentals)
- "Vacation Dining" (dining while traveling)
- "Sightseeing & Tours" (tours, excursions)
- "Souvenirs" (souvenir shops)
- "Travel Insurance" (travel insurance)

GIFTS & DONATIONS:
- "Birthday Gifts" (gift shops, birthday presents)
- "Holiday Gifts" (Christmas, holiday shopping)
- "Wedding/Party Gifts" (wedding gifts, party supplies)
- "Charitable Donations" (charity donations, NGOs)
- "Religious Tithing" (church/religious contributions)
- "Political Contributions" (political donations)

MISCELLANEOUS:
- "Cash Withdrawals" (ATM withdrawals)
- "Reimbursements (Pending)" (pending reimbursements)
- "Adjustment / Correction" (bank adjustments)
- "Unknown Transaction" (cannot determine category)

For each transaction, provide:
1. category: The EXACT sub-category string from the list above
2. confidence: Your confidence level (0.0-1.0) based on how clear the categorization is
3. store_name: A cleaned, readable version of the merchant name (proper case, remove garbage characters)

TIPS FOR BANK TRANSACTIONS:
- Supermarket transactions (Colruyt, Delhaize, Carrefour, Aldi, Lidl) -> "Pantry Staples (Pasta/Rice/Oil)" (general grocery)
- Gas stations (TotalEnergies, Shell, Q8) -> "Fuel (Gas/Diesel/Electric)"
- Pharmacies (Apotheek, Pharmacie) -> "Pharmacy & Prescriptions"
- Telecom (Proximus, Telenet, Orange, Base) -> "Mobile Phone Plan" or "Internet / Wi-Fi" depending on context
- Insurance companies (AG, Ethias, AXA) -> match to the appropriate insurance sub-category
- IBAN transfers with no clear merchant -> look at description for clues; use "Unknown Transaction" if truly unclear
- Belgian/French/Dutch merchant names are common - interpret them correctly

Return ONLY valid JSON in this exact format:
{
  "suggestions": [
    {
      "index": 0,
      "category": "Pantry Staples (Pasta/Rice/Oil)",
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
                category="Unknown Transaction",
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
                    category="Unknown Transaction",
                    confidence=0.5,
                    reasoning="No suggestion returned",
                )

            suggestion = suggestions[0]
            category_str = suggestion.get("category", "Unknown Transaction")
            registry = get_category_registry()
            if not registry.is_valid(category_str):
                matched = registry.find_closest_match(category_str)
                category_str = matched if matched else "Unknown Transaction"

            confidence = float(suggestion.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))

            return CategorySuggestion(
                category=category_str,
                confidence=confidence,
                reasoning=suggestion.get("store_name"),
            )

        except json.JSONDecodeError as e:
            return CategorySuggestion(
                category="Unknown Transaction",
                confidence=0.0,
                reasoning="Failed to parse AI response",
            )
        except Exception as e:
            return CategorySuggestion(
                category="Unknown Transaction",
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

            registry = get_category_registry()
            for i in range(len(transactions)):
                suggestion = suggestions_by_index.get(i, {})

                category_str = suggestion.get("category", "Unknown Transaction")
                if not registry.is_valid(category_str):
                    matched = registry.find_closest_match(category_str)
                    category_str = matched if matched else "Unknown Transaction"

                confidence = float(suggestion.get("confidence", 0.5))
                confidence = max(0.0, min(1.0, confidence))

                results.append(
                    BulkCategorySuggestion(
                        transaction_index=i,
                        category=category_str,
                        confidence=confidence,
                        store_name=suggestion.get("store_name"),
                    )
                )

            return results

        except json.JSONDecodeError as e:
            raise GeminiAPIError(
                "Failed to parse Gemini response",
                details={"error_type": "parse_error", "error": str(e)},
            )
        except Exception as e:
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

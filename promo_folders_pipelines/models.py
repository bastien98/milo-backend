"""
PromoItem dataclass — display-ready fields for the iOS consumer app.

Every field is either displayed directly in the app or used for
Pinecone search/filtering. No raw OCR or data-platform fields.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class PromoItem:
    """A single promotional item extracted from a store folder."""

    # --- Display fields (Gemini-generated) ---
    display_name: str                          # Title Case: Brand + product + variant + size
    display_mechanism: str                     # Standardized promo label: "1+1 Gratis", "-25%"
    display_description: str                   # Plain-language deal explanation in Dutch
    display_savings_label: str                 # "1 Gratis Item", "Bespaar €3.00"
    display_unit_price: Optional[str] = None   # "€0.66/L", "€12.50/kg" (null if no size info)

    # --- Pricing (Gemini-extracted, mandatory) ---
    original_price: float = 0.0                # Regular price before promo
    promo_price: float = 0.0                   # Price of ONE item as shown on shelf
    savings_amount: float = 0.0                # Total euro savings when completing the deal

    # --- Category (for search/filtering) ---
    granular_category: str = ""                # From 238-item category list
    parent_category: str = ""                  # Derived from granular

    # --- Pipeline metadata (not from Gemini) ---
    validity_start: Optional[str] = None
    validity_end: Optional[str] = None
    source_retailer: str = ""
    source_type: str = "folder"
    page_number: Optional[int] = None           # Page in the PDF where this item appears
    promo_folder_url: Optional[str] = None

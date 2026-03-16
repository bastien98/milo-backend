"""
PromoItem dataclass — aligned with receipt OCR field definitions.

Fields map to Pinecone metadata and match the naming conventions
used in app/services/gemini_vision_service.py.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class PromoItem:
    """A single promotional item extracted from a store folder."""

    original_description: str         # Full text as printed in folder
    normalized_name: str              # Lowercase, EXCLUDES brand, INCLUDES variant/flavour
    normalized_brand: Optional[str]   # Lowercase brand (aligned w/ vision service)
    is_premium: bool                  # National brand = true, house brand = false
    packaging_type: Optional[str]     # Container format: blik, fles, pet, zak, pot, etc.
    granular_category: str            # From categories list
    parent_category: str              # Derived from granular
    original_price: Optional[float]
    promo_price: Optional[float]
    promo_mechanism: Optional[str]
    pack_size: Optional[int]          # Multi-pack count (aligned w/ dp_pack_quantity)
    content_value: Optional[float]    # Per-item size number (aligned w/ dp_per_item_size)
    content_unit: Optional[str]       # Unit string (aligned w/ dp_pack_unit)
    unit_info: Optional[str]          # Raw unit string from folder (e.g. "6x33cl")
    validity_start: Optional[str]
    validity_end: Optional[str]
    source_retailer: str
    source_type: str = "folder"
    page_number: Optional[int] = None
    promo_folder_url: Optional[str] = None

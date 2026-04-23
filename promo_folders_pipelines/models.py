"""
PromoItem dataclass — display-ready fields for the iOS consumer app.

Every field is either displayed directly in the app or used for
cross-store comparison / filtering.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PromoItem:
    """A single promotional item extracted from a store folder."""

    # --- Identity (Gemini-extracted) ---
    display_name: str                           # Title Case product label: product + variant + size
    primary_brand: Optional[str] = None         # Most prominent brand ('Coca-Cola'); null for generic
    additional_brands: list[str] = field(default_factory=list)
    # Brands listed on the same multi-product tile ('Fanta', 'Sprite')

    # --- Display (Python-derived via mechanism.py) ---
    display_mechanism: str = ""                 # Canonical Dutch label: '1+1 Gratis', '-25%', '-25% Vanaf 2 Verpakkingen'
    display_description: str = ""               # Plain-language deal explanation in Dutch
    display_savings_label: str = ""             # User-facing savings chip
    display_unit_price: Optional[str] = None    # '€0.66/L', '€12.50/kg' — Python-computed

    # --- Canonical mechanism (Gemini-extracted, feeds display_*) ---
    mechanism_kind: str = "price_reduction"     # One of mechanism.MechanismKind
    mechanism_x: Optional[float] = None
    mechanism_y: Optional[float] = None
    promo_campaign: Optional[str] = None        # Store marketing banner: 'Bonus', 'Prix Choc', etc.

    # --- Pricing ---
    original_price: Optional[float] = None      # Struck-through / 'was' price
    promo_price: Optional[float] = None         # Shelf price
    stated_savings: Optional[float] = None      # Explicitly-printed savings (e.g. 'Bespaar €3')
    savings_amount: float = 0.0                 # Python-derived total euro savings
    min_purchase_qty: int = 1                   # Python-derived from mechanism
    promo_depth: float = 0.0                    # Python-derived effective per-item discount %

    # --- Unit pricing (Python-computed from pack_size_*) ---
    unit_price_value: Optional[float] = None    # Numeric €/canonical_unit
    unit_price_unit: Optional[str] = None       # 'kg' | 'l' | 'stuk' | 'rol'
    unit_price_quality: Optional[str] = None    # 'high' | 'medium' | 'low' | 'missing' | 'invalid'

    # --- Pack size (Gemini-extracted observable tokens) ---
    pack_size_value: Optional[float] = None
    pack_size_unit: Optional[str] = None        # 'g'|'kg'|'ml'|'cl'|'l'|'stuk'|'rol'|'capsule'|'tab'|'doekje'|'zakje'
    pack_count: int = 1

    # --- Category (Gemini-emits granular; Python derives the parent consumer bucket) ---
    granular_category: str = "Other"   # 111-item taxonomy — powers similarity ranking
    category: str = ""                 # Parent category (~22 values) — what iOS displays

    # --- Verbatim tile text (Gemini-extracted, Markdown-formatted, displayed as-is in iOS) ---
    promo_text_markdown: Optional[str] = None

    # --- Pipeline metadata (not from Gemini) ---
    validity_start: Optional[str] = None
    validity_end: Optional[str] = None
    source_retailer: str = ""
    source_type: str = "folder"
    page_number: Optional[int] = None
    promo_folder_url: Optional[str] = None

    # --- Geometry (Gemini-extracted, then refined by pass-2 validation; stored 0-1 normalized) ---
    bbox: Optional[dict] = None                 # Product-only bbox
    tile_bbox: Optional[dict] = None            # Full promo tile bbox

    # --- Product image URLs (persisted to DB, served from R2) ---
    thumbnail_url: Optional[str] = None
    image_url: Optional[str] = None
    hero_url: Optional[str] = None

    # --- Coupon fields (set by pipeline when tile classified as coupon + barcode decoded) ---
    is_coupon: bool = False
    coupon_type: Optional[str] = None               # loyalty_points | cashback | free_product | percent_off_coupon | other
    coupon_barcode_value: Optional[str] = None      # decoded digit string, e.g. '0453697700003'
    coupon_barcode_format: Optional[str] = None     # 'EAN-13' | 'Code-128' | ...
    coupon_value: Optional[float] = None            # points / €-off / %-off
    coupon_min_purchase: Optional[str] = None       # verbatim trigger: '1 pot Natù-fruitspread'
    coupon_validity_end: Optional[str] = None       # YYYY-MM-DD, coupon-level (differs from folder)
    barcode_bbox: Optional[dict] = None             # normalized 0-1, same shape as bbox / tile_bbox

    @property
    def normalized_brand(self) -> Optional[str]:
        """Lowercase primary_brand — kept as a property for backward compat with similarity search."""
        return self.primary_brand.lower() if self.primary_brand else None

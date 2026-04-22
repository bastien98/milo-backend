from typing import Any, Optional, List
from pydantic import BaseModel, Field


class PromoStoreItem(BaseModel):
    item_key: Optional[str] = None
    brand: str = ""
    product_name: str
    original_price: float
    promo_price: float
    savings: float
    min_purchase_qty: int = 1
    discount_percentage: int
    mechanism: str
    validity_end: str
    promo_folder_url: Optional[str] = None
    page_number: Optional[int] = None
    display_name: Optional[str] = None
    display_mechanism: Optional[str] = None
    display_description: Optional[str] = None
    display_unit_price: Optional[str] = None
    display_savings_label: Optional[str] = None
    thumbnail_url: Optional[str] = None
    image_url: Optional[str] = None
    hero_url: Optional[str] = None  # Full-tile crop for the product-detail view (product + price label + brand + badge)
    store_name: Optional[str] = None
    price_unavailable: bool = False  # True for assortment tiles with no printed price — iOS renders "Prijs in winkel"
    # --- New canonical fields (iOS can adopt incrementally) ---
    primary_brand: Optional[str] = None
    additional_brands: Optional[List[str]] = None
    mechanism_kind: Optional[str] = None
    mechanism_x: Optional[float] = None
    mechanism_y: Optional[float] = None
    promo_campaign: Optional[str] = None
    category: Optional[str] = None  # Parent consumer category (~22 values)
    promo_text_markdown: Optional[str] = None  # Verbatim tile text as Markdown


# ---------------------------------------------------------------------------
# Similar Promos (carousel on promo detail sheet)
# ---------------------------------------------------------------------------

class SimilarPromosSource(BaseModel):
    id: str
    display_name: str
    display_brand: Optional[str] = None
    normalized_brand: Optional[str] = None
    granular_category: str
    source_retailer: str


class SimilarPromosResponse(BaseModel):
    source: SimilarPromosSource
    items: List[PromoStoreItem]
    generated_at: str


# ---------------------------------------------------------------------------
# Promo Interaction Events (telemetry for folder + carousel)
# ---------------------------------------------------------------------------

class PromoInteractionEventCreate(BaseModel):
    event_type: str = Field(
        ...,
        description="Event name — e.g. 'deal_opened', 'similar_promo_clicked'",
        max_length=64,
    )
    promo_item_id: Optional[str] = None
    source_item_id: Optional[str] = None
    store_name: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Promo Folders (browsable folder pages from R2)
# ---------------------------------------------------------------------------

class PromoFolderHotspot(BaseModel):
    """A tappable product hotspot on a folder page."""
    item_id: str
    page_number: int
    tile_bbox_x_min: float
    tile_bbox_y_min: float
    tile_bbox_x_max: float
    tile_bbox_y_max: float
    display_name: str
    display_brand: Optional[str] = None
    display_mechanism: str
    original_price: Optional[float] = None
    promo_price: Optional[float] = None
    savings_amount: float = 0.0
    discount_percentage: int
    min_purchase_qty: int = 1
    validity_end: str
    thumbnail_url: Optional[str] = None
    image_url: Optional[str] = None
    hero_url: Optional[str] = None  # Full-tile crop for the product-detail view (product + price label + brand + badge)
    store_name: str
    price_unavailable: bool = False  # True for assortment tiles with no printed price
    mechanism_kind: Optional[str] = None
    promo_campaign: Optional[str] = None
    promo_text_markdown: Optional[str] = None


class PromoFolderPage(BaseModel):
    """A single page image from a promo folder."""
    page_number: int
    image_url: str
    hotspots: List[PromoFolderHotspot] = []


class PromoFolderInfo(BaseModel):
    """A single promo folder (one PDF/leaflet) for a store."""
    folder_id: str
    store_id: str
    store_display_name: str
    folder_name: str
    source_url: str
    validity_start: str
    validity_end: str
    page_count: int
    pages: List[PromoFolderPage]


class PromoFoldersResponse(BaseModel):
    """Response for GET /api/v2/promos/folders."""
    folders: List[PromoFolderInfo]

from typing import Any, Optional, List
from pydantic import BaseModel, Field

from app.models.enums import PromoReportEventType, PromoReportStatus


class PromoStoreItem(BaseModel):
    item_key: Optional[str] = None
    brand: str = ""
    product_name: str
    original_price: float
    promo_price: float
    savings: float
    savings_amount: Optional[float] = None
    min_purchase_qty: int = 1
    effective_unit_price: Optional[float] = None
    discount_percentage: int
    mechanism: str
    validity_start: str
    validity_end: str
    promo_folder_url: Optional[str] = None
    page_number: Optional[int] = None
    display_name: Optional[str] = None
    display_mechanism: Optional[str] = None
    display_description: Optional[str] = None
    display_unit_price: Optional[str] = None
    display_savings_label: Optional[str] = None
    bucket: Optional[str] = None
    bucket_label: Optional[str] = None
    thumbnail_url: Optional[str] = None
    image_url: Optional[str] = None


class PromoStore(BaseModel):
    store_name: str
    total_savings: float
    validity_end: str
    items: List[PromoStoreItem]


class PromoStoreBreakdown(BaseModel):
    store: str
    items: int
    savings: float


class PromoSummary(BaseModel):
    total_items: int
    total_savings: float
    stores_breakdown: List[PromoStoreBreakdown]
    best_value_store: Optional[str] = None
    best_value_savings: float
    best_value_items: int


class PromoWeek(BaseModel):
    start: str
    end: str
    label: str
    iso_year: int
    iso_week: int


class PromoRecommendationResponse(BaseModel):
    report_id: Optional[str] = None
    report_status: PromoReportStatus
    message: str
    generated_at: Optional[str] = None
    weekly_savings: float
    deal_count: int
    promo_week: PromoWeek
    stores: List[PromoStore]
    preferred_stores: List[str] = []
    summary: PromoSummary


class PromoReportEventCreate(BaseModel):
    report_id: str
    event_type: PromoReportEventType
    item_key: Optional[str] = None
    store_name: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Promo Search
# ---------------------------------------------------------------------------

class PromoSearchRequest(BaseModel):
    """Request body for POST /api/v2/promos/search."""
    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Product name or description to search for",
    )
    stores: List[str] = Field(
        ...,
        min_length=1,
        description="Canonical store names to filter by",
    )


class PromoSearchResult(BaseModel):
    """A single promo search result."""
    product_name: str
    brand: Optional[str] = None
    category: str
    store: str
    original_price: Optional[float] = None
    promo_price: Optional[float] = None
    savings: Optional[float] = None
    savings_amount: Optional[float] = None
    discount_percent: Optional[float] = None
    mechanism: Optional[str] = None
    validity_start: Optional[str] = None
    validity_end: Optional[str] = None
    display_name: Optional[str] = None
    display_mechanism: Optional[str] = None
    display_description: Optional[str] = None
    display_unit_price: Optional[str] = None
    display_savings_label: Optional[str] = None
    relevance_score: float
    promo_folder_url: Optional[str] = None


class PromoSearchResponse(BaseModel):
    """Response for POST /api/v2/promos/search."""
    query: str
    stores: List[str]
    result_count: int
    results: List[PromoSearchResult]


class PromoStoreOption(BaseModel):
    """A store available for promo search filtering."""
    id: str
    name: str
    has_promos: bool


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
    original_price: float
    promo_price: float
    savings_amount: float
    discount_percentage: int
    min_purchase_qty: int = 1
    validity_end: str
    thumbnail_url: Optional[str] = None
    image_url: Optional[str] = None
    store_name: str


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

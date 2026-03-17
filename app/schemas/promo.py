from typing import Any, Optional, List
from pydantic import BaseModel

from app.models.enums import PromoReportEventType, PromoReportStatus


class PromoTopPick(BaseModel):
    item_key: Optional[str] = None
    brand: str
    product_name: str
    emoji: str
    store: str
    original_price: float
    promo_price: float
    savings: float
    discount_percentage: int
    mechanism: str
    validity_start: str
    validity_end: str
    reason: str
    page_number: Optional[int] = None
    promo_folder_url: Optional[str] = None


class PromoStoreItem(BaseModel):
    item_key: Optional[str] = None
    brand: str
    product_name: str
    emoji: str
    original_price: float
    promo_price: float
    savings: float
    discount_percentage: int
    mechanism: str
    validity_start: str
    validity_end: str
    page_number: Optional[int] = None
    promo_folder_url: Optional[str] = None


class PromoStore(BaseModel):
    store_name: str
    store_color: str
    total_savings: float
    validity_end: str
    items: List[PromoStoreItem]
    tip: str


class PromoSmartSwitch(BaseModel):
    from_brand: str
    to_brand: str
    emoji: str
    product_type: str
    savings: float
    mechanism: str
    reason: str


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
    closing_nudge: str


class PromoWeek(BaseModel):
    start: str
    end: str
    label: str
    iso_year: int
    iso_week: int


class GeminiItemAnnotation(BaseModel):
    """Per-item AI annotation returned by Gemini."""

    item_key: str
    reason: str


class GeminiSmartSwitchCandidate(BaseModel):
    """Pre-computed smart switch suggestion from Gemini."""

    from_brand: str
    to_brand: str
    emoji: str
    product_type: str
    savings: float
    mechanism: str
    store_name: str
    reason: str


class GeminiStoreTip(BaseModel):
    """Per-store personalized tip from Gemini."""

    store_name: str
    tip: str


class GeminiCandidateOutput(BaseModel):
    """Schema passed to Gemini response_schema for per-item candidate annotations.

    Gemini annotates individual items rather than producing a full report.
    Assembly into the final response happens server-side at serve time.
    """

    item_annotations: List[GeminiItemAnnotation]
    store_tips: List[GeminiStoreTip]
    smart_switch_candidates: List[GeminiSmartSwitchCandidate]
    closing_nudge: str


class PromoRecommendationResponse(BaseModel):
    report_id: Optional[str] = None
    report_status: PromoReportStatus
    message: str
    generated_at: Optional[str] = None
    weekly_savings: float
    deal_count: int
    promo_week: PromoWeek
    top_picks: List[PromoTopPick]
    stores: List[PromoStore]
    smart_switch: Optional[PromoSmartSwitch] = None
    summary: PromoSummary


class PromoReportEventCreate(BaseModel):
    report_id: str
    event_type: PromoReportEventType
    item_key: Optional[str] = None
    store_name: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None

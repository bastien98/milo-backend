from typing import Optional, List
from pydantic import BaseModel


class PromoTopPick(BaseModel):
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


class GeminiPromoOutput(BaseModel):
    """Schema passed to Gemini response_schema to enforce structured output.

    Does NOT include promo_week (computed server-side).
    """

    weekly_savings: float
    deal_count: int
    top_picks: List[PromoTopPick]
    stores: List[PromoStore]
    smart_switch: Optional[PromoSmartSwitch] = None
    summary: PromoSummary


class PromoRecommendationResponse(BaseModel):
    weekly_savings: float
    deal_count: int
    promo_week: PromoWeek
    top_picks: List[PromoTopPick]
    stores: List[PromoStore]
    smart_switch: Optional[PromoSmartSwitch] = None
    summary: PromoSummary

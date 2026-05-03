from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, model_validator


# ---------------------------------------------------------------------------
# User-facing schemas
# ---------------------------------------------------------------------------

class BrandCashbackDealResponse(BaseModel):
    """A single campaign as returned to iOS clients, including per-user status."""
    id: str
    brand_name: str
    product_name: str
    description: str
    cashback_amount: float        # euros (cents / 100)
    image_url: Optional[str] = None       # hero (original aspect, ~1200px max), used in detail sheet
    image_thumb_url: Optional[str] = None  # thumbnail (400x400 square crop), used in grid cards
    valid_from: datetime
    valid_until: datetime
    eligible_stores: List[str]
    requires_store: bool
    user_status: str              # "available" | "claimed" | "earned" | "expired"
    earned_at: Optional[datetime] = None  # set when user_status == "earned"
    # Coupon-grade fields
    terms: Optional[str] = None
    how_it_works: List[str] = []
    claim_window_days: int = 14
    max_redemptions_per_user: int = 1
    total_redemption_cap: Optional[int] = None
    category: Optional[str] = None
    featured: bool = False
    # Derived
    current_redemptions: int = 0
    eligible_skus: List[str] = []
    claim_expires_at: Optional[datetime] = None  # set when user_status == "claimed"

    class Config:
        from_attributes = True


class BrandCashbackClaimResponse(BaseModel):
    campaign_id: str
    status: str
    claimed_at: datetime


# ---------------------------------------------------------------------------
# Admin schemas
# ---------------------------------------------------------------------------

class AdminLineItemCreate(BaseModel):
    store_name: str
    exact_line_item: str
    alt_line_items: List[str] = []
    notes: Optional[str] = None


class AdminLineItemResponse(BaseModel):
    id: str
    campaign_id: str
    store_name: str
    exact_line_item: str
    alt_line_items: List[str]
    notes: Optional[str]
    verified_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class AdminCampaignCreate(BaseModel):
    brand_name: str
    product_name: str
    description: str = ""
    cashback_amount_cents: int    # integer cents, e.g. 50 = €0.50
    valid_from: datetime
    valid_until: datetime
    eligible_stores: List[str] = []
    requires_store: bool = False
    terms: Optional[str] = None
    how_it_works: List[str] = []
    claim_window_days: int = 14
    max_redemptions_per_user: int = 1
    total_redemption_cap: Optional[int] = None
    category: Optional[str] = None
    featured: bool = False

    @model_validator(mode="after")
    def _check_dates(self):
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        return self


class AdminCampaignUpdate(BaseModel):
    brand_name: Optional[str] = None
    product_name: Optional[str] = None
    description: Optional[str] = None
    cashback_amount_cents: Optional[int] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    eligible_stores: Optional[List[str]] = None
    requires_store: Optional[bool] = None
    is_active: Optional[bool] = None
    terms: Optional[str] = None
    how_it_works: Optional[List[str]] = None
    claim_window_days: Optional[int] = None
    max_redemptions_per_user: Optional[int] = None
    total_redemption_cap: Optional[int] = None
    category: Optional[str] = None
    featured: Optional[bool] = None


class AdminCampaignResponse(BaseModel):
    id: str
    brand_name: str
    product_name: str
    description: str
    cashback_amount_cents: int
    image_url: Optional[str] = None
    image_thumb_url: Optional[str] = None
    valid_from: datetime
    valid_until: datetime
    eligible_stores: List[str]
    requires_store: bool
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]
    claims_count: int = 0
    earned_count: int = 0
    # Coupon-grade fields
    terms: Optional[str] = None
    how_it_works: List[str] = []
    claim_window_days: int = 14
    max_redemptions_per_user: int = 1
    total_redemption_cap: Optional[int] = None
    category: Optional[str] = None
    featured: bool = False
    # Derived
    current_redemptions: int = 0
    eligible_skus: List[str] = []

    class Config:
        from_attributes = True


class AdminCampaignDeletePreview(BaseModel):
    earned_count: int
    would_hard_delete: bool


class AdminStatsResponse(BaseModel):
    total_active_campaigns: int
    total_claims: int
    total_earned_claims: int
    total_earned_euros: float
    avg_cashback_euros: float

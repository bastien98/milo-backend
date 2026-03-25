from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, computed_field


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
    image_system_name: str        # SF Symbol name
    valid_from: datetime
    valid_until: datetime
    eligible_stores: List[str]
    requires_store: bool
    user_status: str              # "available" | "claimed" | "earned" | "expired"
    earned_at: Optional[datetime] = None  # set when user_status == "earned"

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
    image_system_name: str = "tag.fill"
    valid_from: datetime
    valid_until: datetime
    eligible_stores: List[str] = []
    requires_store: bool = False


class AdminCampaignUpdate(BaseModel):
    brand_name: Optional[str] = None
    product_name: Optional[str] = None
    description: Optional[str] = None
    cashback_amount_cents: Optional[int] = None
    image_system_name: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    eligible_stores: Optional[List[str]] = None
    requires_store: Optional[bool] = None
    is_active: Optional[bool] = None


class AdminCampaignResponse(BaseModel):
    id: str
    brand_name: str
    product_name: str
    description: str
    cashback_amount_cents: int
    image_system_name: str
    valid_from: datetime
    valid_until: datetime
    eligible_stores: List[str]
    requires_store: bool
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]
    claims_count: int = 0
    earned_count: int = 0

    class Config:
        from_attributes = True


class AdminStatsResponse(BaseModel):
    total_active_campaigns: int
    total_claims: int
    total_earned_claims: int
    total_earned_euros: float
    avg_cashback_euros: float

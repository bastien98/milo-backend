from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Pending-review summaries (embedded in deal/claim responses)
# ---------------------------------------------------------------------------

class PendingReviewSummary(BaseModel):
    """Embedded on a deal when the user has a pending-review row for it."""
    id: str
    receipt_id: str
    candidate_string: str
    created_at: datetime


class RecentDenialSummary(BaseModel):
    """Embedded on a deal when the user has a denied review in the last 7 days."""
    id: str
    receipt_id: str
    denied_at: datetime
    reason: str


# ---------------------------------------------------------------------------
# User-facing schemas
# ---------------------------------------------------------------------------

class BrandCashbackDealResponse(BaseModel):
    """A single campaign as returned to iOS clients, including per-user status.

    user_status semantics:
      - "available": user has no claim for this campaign yet.
      - "claimed":   user has a claim and can still earn (earnings < max).
      - "earned":    user has reached max_redemptions_per_user.
    Expired campaigns and campaigns with the global cap exhausted are filtered
    out server-side and never returned with one of these statuses. The
    `pending_review` field is set when there is an open admin review for this
    user+campaign — the iOS layer renders it as a separate "Pending review"
    status without changing the underlying claim model.
    """
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
    user_status: str
    earned_at: Optional[datetime] = None  # most recent earning, if any
    # Coupon-grade fields
    terms: Optional[str] = None
    how_it_works: List[str] = []
    max_redemptions_per_user: int = 1
    total_redemption_cap: Optional[int] = None
    category: Optional[str] = None
    featured: bool = False
    # Derived
    current_redemptions: int = 0          # earnings across all users (campaign cap progress)
    eligible_skus: List[str] = []
    # Per-user progress for max_redemptions_per_user
    earnings_count: int = 0               # how many times THIS user has earned
    claimed_at: Optional[datetime] = None  # set when user has a claim
    # Manual-review queue surface
    pending_review: Optional[PendingReviewSummary] = None
    recent_denial: Optional[RecentDenialSummary] = None

    class Config:
        from_attributes = True


class BrandCashbackClaimResponse(BaseModel):
    campaign_id: str
    claimed_at: datetime


class BrandCashbackPendingMatchResponse(BaseModel):
    """Full pending-match record for /my-pending-reviews and admin views."""
    id: str
    user_id: str
    campaign_id: str
    receipt_id: str
    candidate_string: str
    matched_line_item_id: Optional[str]
    match_score: float
    store_name: Optional[str]
    status: str
    created_at: datetime
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    denial_reason: Optional[str] = None
    earning_id: Optional[str] = None
    # Admin context (populated when surfaced via admin endpoints)
    brand_name: Optional[str] = None
    product_name: Optional[str] = None
    cashback_amount_cents: Optional[int] = None
    canonical_line_item: Optional[str] = None
    canonical_alts: List[str] = []
    receipt_image_url: Optional[str] = None

    class Config:
        from_attributes = True


class AdminApprovePendingRequest(BaseModel):
    add_to_alts: bool = True


class AdminDenyPendingRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


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
    claims_count: int = 0     # distinct users who have claimed
    earned_count: int = 0     # total earning events
    # Coupon-grade fields
    terms: Optional[str] = None
    how_it_works: List[str] = []
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
    pending_reviews: int = 0

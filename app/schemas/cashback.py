from datetime import date, datetime
from typing import Optional, List

from pydantic import BaseModel, computed_field

from app.models.enums import CashbackStatus

# 10,000 points = EUR 10.00
POINTS_PER_EURO = 1000


class KickstartProgressResponse(BaseModel):
    tickets_completed: int
    total_tickets: int = 3
    is_completed: bool


class CashbackTransactionResponse(BaseModel):
    id: str
    receipt_id: str
    receipt_total: float
    points_total: int = 0
    fixed_points: int = 0
    grote_kar_points: int = 0
    kickstart_bonus_points: int = 0
    spin_type: Optional[str] = None
    is_kickstart: bool = False
    is_streak_saver: bool = False
    status: CashbackStatus
    created_at: datetime
    store_name: Optional[str] = None
    receipt_date: Optional[date] = None
    is_referral_reward: bool = False
    is_streak_reward: bool = False

    # Legacy fields kept for backward compat
    cashback_amount: float = 0.0
    effective_rate: float = 0.0
    spins_awarded: int = 0

    class Config:
        from_attributes = True


class CashbackBalanceResponse(BaseModel):
    points_balance: int = 0
    total_points_earned: int = 0
    total_points_paid_out: int = 0
    standard_spins: int = 0
    premium_spins: int = 0
    tier_level: str = "bronze"
    kickstart_progress: Optional[KickstartProgressResponse] = None
    euro_value: float = 0.0
    minimum_payout_points: int = 10000
    can_withdraw: bool = False

    # Legacy fields for backward compat
    is_gold_tier: bool = False
    spins_available: int = 0
    current_balance: float = 0.0
    total_earned: float = 0.0
    total_paid_out: float = 0.0

    class Config:
        from_attributes = True


class CashbackSummaryResponse(BaseModel):
    balance: CashbackBalanceResponse
    recent_transactions: List[CashbackTransactionResponse]
    avg_points_per_receipt: float = 0.0
    total_receipts_with_rewards: int = 0
    tier_level: str = "bronze"

    # Legacy
    avg_cashback_per_receipt: float = 0.0
    total_receipts_with_cashback: int = 0
    is_gold_tier: bool = False


class CashbackClaimResponse(BaseModel):
    receipt_id: str
    points_total: int = 0
    spin_type: Optional[str] = None
    new_points_balance: int = 0
    euro_value: float = 0.0

    # Legacy fields
    cashback_amount: float = 0.0
    spins_awarded: int = 0
    new_balance: float = 0.0


class CashbackHistoryResponse(BaseModel):
    transactions: List[CashbackTransactionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

from datetime import date, datetime
from typing import Optional, List

from pydantic import BaseModel

from app.models.enums import CashbackStatus


class CashbackTransactionResponse(BaseModel):
    id: str
    receipt_id: str
    receipt_total: float
    cashback_amount: float
    effective_rate: float
    status: CashbackStatus
    created_at: datetime
    store_name: Optional[str] = None
    receipt_date: Optional[date] = None
    spins_awarded: int = 0

    class Config:
        from_attributes = True


class CashbackBalanceResponse(BaseModel):
    total_earned: float
    total_paid_out: float
    current_balance: float
    is_gold_tier: bool = False
    spins_available: int = 0

    class Config:
        from_attributes = True


class CashbackSummaryResponse(BaseModel):
    balance: CashbackBalanceResponse
    recent_transactions: List[CashbackTransactionResponse]
    avg_cashback_per_receipt: float
    total_receipts_with_cashback: int
    is_gold_tier: bool = False


class CashbackSegment(BaseModel):
    segment: int
    slice_start: float
    slice_end: float
    rate: float
    cashback: float


class CashbackCalculationPreview(BaseModel):
    receipt_total: float
    cashback_amount: float
    effective_rate: float
    segments: List[CashbackSegment]


class CashbackHistoryResponse(BaseModel):
    transactions: List[CashbackTransactionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

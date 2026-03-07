from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel

from app.models.enums import WithdrawalStatus


class WithdrawalCreateRequest(BaseModel):
    amount: float
    iban: str


class WithdrawalResponse(BaseModel):
    id: str
    amount: float
    iban_last4: str
    status: WithdrawalStatus
    fraud_check_passed: bool
    admin_notes: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None
    paid_out_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WithdrawalInfoResponse(BaseModel):
    current_balance: float
    max_withdrawable: float
    available_amounts: List[float]
    has_pending_withdrawal: bool
    active_withdrawal: Optional[WithdrawalResponse] = None
    last_iban: Optional[str] = None
    last_iban_last4: Optional[str] = None
    can_withdraw: bool
    cannot_withdraw_reason: Optional[str] = None


class WithdrawalCreateResponse(BaseModel):
    id: str
    amount: float
    iban_last4: str
    status: WithdrawalStatus
    fraud_check_passed: bool
    fraud_check_details: Optional[dict] = None
    new_balance: float


class WithdrawalHistoryResponse(BaseModel):
    withdrawals: List[WithdrawalResponse]
    has_pending: bool


class WithdrawalAdminReviewRequest(BaseModel):
    action: str  # "approve" or "reject"
    admin_notes: Optional[str] = None


class WithdrawalAdminListItem(BaseModel):
    id: str
    user_id: str
    user_email: Optional[str] = None
    amount: float
    iban: str
    iban_last4: str
    status: WithdrawalStatus
    fraud_check_passed: bool
    fraud_check_details: Optional[dict] = None
    admin_notes: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None
    paid_out_at: Optional[datetime] = None

    class Config:
        from_attributes = True

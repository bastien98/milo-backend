from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel

from app.models.enums import CharityDonationStatus


class CharityItem(BaseModel):
    id: str
    name: str
    description: str
    icon: str       # SF Symbol name for iOS
    color: str      # color name used on iOS
    community_total: float = 0.0   # total donated by all users
    user_total: float = 0.0        # total donated by the requesting user


class CharityListResponse(BaseModel):
    charities: List[CharityItem]
    user_balance: float


class CharityDonateRequest(BaseModel):
    charity_id: str
    amount: float


class CharityDonateResponse(BaseModel):
    id: str
    charity_id: str
    charity_name: str
    amount: float
    status: CharityDonationStatus
    fraud_check_passed: bool
    new_balance: float


class CharityDonationItem(BaseModel):
    id: str
    charity_id: str
    charity_name: str
    amount: float
    status: CharityDonationStatus
    created_at: datetime
    transferred_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CharityHistoryResponse(BaseModel):
    donations: List[CharityDonationItem]
    total_donated: float


class CharityAdminDonationItem(BaseModel):
    id: str
    user_id: str
    user_email: Optional[str] = None
    charity_id: str
    charity_name: str
    amount: float
    status: CharityDonationStatus
    fraud_check_passed: bool
    created_at: datetime
    transferred_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CharityAdminSummaryItem(BaseModel):
    charity_id: str
    charity_name: str
    pending_total: float
    pending_count: int
    transferred_total: float
    transferred_count: int

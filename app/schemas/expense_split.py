from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


# Friend Color Palette - 8 vibrant colors
FRIEND_COLORS = [
    "#FF6B6B",  # Coral
    "#4ECDC4",  # Ocean Blue
    "#FFE66D",  # Sunny Yellow
    "#95E879",  # Forest Green
    "#B388EB",  # Lavender
    "#FF9F45",  # Tangerine
    "#FF69B4",  # Hot Pink
    "#00CED1",  # Teal
]


# MARK: - Participant Schemas


class SplitParticipantCreate(BaseModel):
    """Schema for creating a new participant in a split."""

    name: str = Field(..., min_length=1, max_length=100)
    color: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")
    custom_amount: Optional[float] = None  # Custom split amount (None = equal split)
    is_me: bool = False  # True if this participant represents the current user


class SplitParticipantResponse(BaseModel):
    """Schema for a participant in a split."""

    id: str
    name: str
    color: str
    display_order: int
    custom_amount: Optional[float] = None  # Custom split amount (None = equal split)
    is_me: bool = False  # True if this participant represents the current user
    created_at: datetime

    class Config:
        from_attributes = True


# MARK: - Assignment Schemas


class SplitAssignmentCreate(BaseModel):
    """Schema for creating a split assignment."""

    transaction_id: str
    participant_ids: List[str] = []


class SplitAssignmentResponse(BaseModel):
    """Schema for a split assignment."""

    id: str
    transaction_id: str
    participant_ids: List[str]
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SplitAssignmentUpdate(BaseModel):
    """Schema for updating a split assignment."""

    participant_ids: List[str]


# MARK: - Expense Split Schemas


class ExpenseSplitCreate(BaseModel):
    """Schema for creating a new expense split."""

    receipt_id: str
    participants: List[SplitParticipantCreate]
    assignments: List[SplitAssignmentCreate]


class ExpenseSplitUpdate(BaseModel):
    """Schema for updating an expense split."""

    participants: Optional[List[SplitParticipantCreate]] = None
    assignments: Optional[List[SplitAssignmentCreate]] = None


class ExpenseSplitResponse(BaseModel):
    """Schema for an expense split response."""

    id: str
    receipt_id: str
    participants: List[SplitParticipantResponse]
    assignments: List[SplitAssignmentResponse]
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# MARK: - Calculation Schemas


class ParticipantTotal(BaseModel):
    """Per-participant total in a split."""

    participant_id: str
    participant_name: str
    participant_color: str
    total_amount: float
    item_count: int
    items: List[dict]  # List of {item_name, item_price, share_amount}


class SplitCalculationResponse(BaseModel):
    """Response with calculated split totals."""

    receipt_id: str
    receipt_total: float
    participant_totals: List[ParticipantTotal]


# MARK: - Recent Friends Schemas


class RecentFriendResponse(BaseModel):
    """Schema for a recent friend."""

    id: str
    name: str
    color: str
    last_used_at: datetime
    use_count: int

    class Config:
        from_attributes = True


class RecentFriendsListResponse(BaseModel):
    """Schema for list of recent friends."""

    friends: List[RecentFriendResponse]


# MARK: - Share Text Schema


class ShareTextRequest(BaseModel):
    """Request to generate shareable text for a split."""

    split_id: str


class ShareTextResponse(BaseModel):
    """Response with shareable text."""

    text: str

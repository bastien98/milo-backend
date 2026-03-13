from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class LotteryStatusResponse(BaseModel):
    eligible: bool
    has_instagram: bool
    has_receipt: bool
    has_share: bool = False
    proof_status: Optional[str] = None
    post_url: Optional[str] = None
    current_month: str
    prize_amount: int
    drawing_status: str
    last_winner: Optional["LotteryWinnerResponse"] = None

    class Config:
        from_attributes = True


class LotteryWinnerResponse(BaseModel):
    name: str
    instagram_handle: str
    month: str


class LotteryDrawingResponse(BaseModel):
    id: str
    month: str
    status: str
    prize_amount_cents: int
    seed: Optional[str] = None
    seed_hash: Optional[str] = None
    winner_user_id: Optional[str] = None
    winner_name: Optional[str] = None
    winner_instagram_handle: Optional[str] = None
    participant_count: int
    post_url: Optional[str] = None
    video_url: Optional[str] = None
    drawn_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class LotteryEntryResponse(BaseModel):
    id: str
    drawing_id: str
    user_id: str
    instagram_handle: Optional[str] = None
    display_name: Optional[str] = None
    has_receipt_activity: bool
    has_instagram_share: bool
    is_eligible: bool
    entry_number: Optional[int] = None
    proof_image_key: Optional[str] = None
    proof_status: Optional[str] = None  # pending_review, approved, rejected

    class Config:
        from_attributes = True


class ToggleShareRequest(BaseModel):
    user_id: str
    shared: bool


class PublishRequest(BaseModel):
    video_url: str


class ApproveProofRequest(BaseModel):
    approved: bool


class SetPostUrlRequest(BaseModel):
    post_url: str


class VideoPropsResponse(BaseModel):
    participants: List[dict]
    winnerIndex: int
    monthLabel: str
    prizeAmount: str
    fairnessHash: str

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SpinRequest(BaseModel):
    """Request to spin the wheel. has_double_next indicates the previous spin was a Double Next."""
    has_double_next: bool = False
    force_segment: Optional[int] = None  # Test mode: force a specific segment index (0-7)


class SpinSegmentResponse(BaseModel):
    index: int
    label: str
    segment_type: str  # cash, mystery, try_again, double_next, jackpot


class SpinResultResponse(BaseModel):
    segment_index: int
    segment_label: str
    segment_type: str
    cash_value: float
    is_jackpot: bool
    is_doubled: bool
    mystery_reveal_value: Optional[float] = None
    grants_free_spin: bool
    grants_double_next: bool
    new_balance: float
    spins_remaining: int

    class Config:
        from_attributes = True


class SpinWheelConfigResponse(BaseModel):
    """Returns the wheel configuration so the frontend can render segments."""
    segments: list[SpinSegmentResponse]
    total_segments: int


class SpinHistoryResponse(BaseModel):
    segment_label: str
    segment_type: str
    cash_value: float
    is_jackpot: bool
    is_doubled: bool
    created_at: datetime

    class Config:
        from_attributes = True

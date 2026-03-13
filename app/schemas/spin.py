from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SpinRequest(BaseModel):
    """Request to spin the wheel."""
    spin_type: str = "standard"  # "standard" or "premium"
    is_respin: bool = False       # True if triggered by a Try Again result
    force_segment: Optional[int] = None  # Test mode: force a specific segment (0-7)

    # Legacy fields kept for compat
    has_double_next: bool = False


class SpinSegmentResponse(BaseModel):
    index: int
    label: str
    segment_type: str  # cash, mystery, try_again, jackpot
    base_value: int = 0


class SpinResultResponse(BaseModel):
    segment_index: int
    segment_label: str
    segment_type: str
    points_value: int
    is_jackpot: bool
    mystery_reveal_value: Optional[int] = None
    grants_free_spin: bool
    spin_type: str
    new_points_balance: int
    standard_spins_remaining: int
    premium_spins_remaining: int

    # Legacy fields for compat
    cash_value: float = 0.0
    is_doubled: bool = False
    grants_double_next: bool = False
    new_balance: float = 0.0
    spins_remaining: int = 0

    class Config:
        from_attributes = True


class SpinWheelConfigResponse(BaseModel):
    """Returns the wheel configuration for the frontend."""
    segments: list[SpinSegmentResponse]
    total_segments: int
    spin_type: str = "standard"


class SpinHistoryResponse(BaseModel):
    segment_label: str
    segment_type: str
    points_value: int = 0
    is_jackpot: bool
    spin_type: Optional[str] = None
    created_at: datetime

    # Legacy
    cash_value: float = 0.0
    is_doubled: bool = False

    class Config:
        from_attributes = True

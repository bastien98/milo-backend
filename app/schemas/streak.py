from typing import Optional, List

from pydantic import BaseModel


class StreakCycleEntry(BaseModel):
    week: int
    cycle_position: int = 0
    label: str
    reward_type: str
    completed: bool


class StreakClaimableReward(BaseModel):
    reward_id: str
    week_number: int
    reward_type: str
    spins_amount: int
    spin_type: Optional[str] = None
    points_amount: int = 0
    streak_level: int = 1

    # Legacy
    cash_amount: float = 0.0


class StreakStatusResponse(BaseModel):
    week_count: int
    streak_level: int = 1
    current_cycle: List[StreakCycleEntry]
    claimable_reward: Optional[StreakClaimableReward] = None
    is_at_risk: bool = False


class StreakClaimResponse(BaseModel):
    success: bool
    reward_type: str
    spins_credited: int
    spin_type: Optional[str] = None
    points_credited: int = 0
    new_points_balance: int = 0
    new_standard_spins: int = 0
    new_premium_spins: int = 0

    # Legacy
    cash_credited: float = 0.0
    new_balance: float = 0.0
    new_spins_available: int = 0

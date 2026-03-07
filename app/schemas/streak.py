from typing import Optional, List

from pydantic import BaseModel


class StreakCycleEntry(BaseModel):
    week: int
    label: str
    reward_type: str
    completed: bool


class StreakClaimableReward(BaseModel):
    reward_id: str
    week_number: int
    reward_type: str
    spins_amount: int
    cash_amount: float


class StreakStatusResponse(BaseModel):
    week_count: int
    current_cycle: List[StreakCycleEntry]
    claimable_reward: Optional[StreakClaimableReward] = None
    is_at_risk: bool = False


class StreakClaimResponse(BaseModel):
    success: bool
    reward_type: str
    spins_credited: int
    cash_credited: float
    new_balance: float
    new_spins_available: int

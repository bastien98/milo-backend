from typing import Optional

from pydantic import BaseModel, Field


class ReferralInfoResponse(BaseModel):
    referral_code: str
    total_referrals: int
    completed_referrals: int
    pending_referrals: int
    total_earned: float
    has_unclaimed_reward: bool = False
    unclaimed_reward_euros: float = 0.0
    unclaimed_reward_spins: int = 0
    unclaimed_referral_id: Optional[str] = None
    unclaimed_referral_role: Optional[str] = None


class ApplyReferralCodeRequest(BaseModel):
    referral_code: str = Field(..., min_length=4, max_length=10)


class ApplyReferralCodeResponse(BaseModel):
    success: bool
    message: str
    referrer_name: Optional[str] = None


class ClaimReferralRewardResponse(BaseModel):
    success: bool
    message: str
    euros_credited: float = 0.0
    spins_credited: int = 0
    new_balance: float = 0.0

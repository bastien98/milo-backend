from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.services.referral_service import ReferralService
from app.schemas.referral import (
    ReferralInfoResponse,
    ApplyReferralCodeRequest,
    ApplyReferralCodeResponse,
    ClaimReferralRewardResponse,
)

router = APIRouter()


@router.get("/info", response_model=ReferralInfoResponse)
async def get_referral_info(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Get the user's referral code and stats. Generates code on first call."""
    svc = ReferralService(db)
    info = await svc.get_referral_info(current_user)
    return ReferralInfoResponse(**info)


@router.post("/apply", response_model=ApplyReferralCodeResponse)
async def apply_referral_code(
    request: ApplyReferralCodeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Apply a referral code. Called by the referee."""
    svc = ReferralService(db)
    result = await svc.apply_referral_code(current_user, request.referral_code)
    return ApplyReferralCodeResponse(**result)


@router.post("/claim", response_model=ClaimReferralRewardResponse)
async def claim_referral_reward(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Claim an unclaimed referral reward. Credits EUR + spins to the user."""
    svc = ReferralService(db)
    result = await svc.claim_referral_reward(current_user)
    await db.commit()
    return ClaimReferralRewardResponse(**result)

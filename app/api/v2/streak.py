import os

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.services.streak_service import StreakService
from app.schemas.streak import (
    StreakStatusResponse,
    StreakClaimResponse,
    StreakCycleEntry,
    StreakClaimableReward,
)

router = APIRouter()

TEST_MODE = os.getenv("STREAK_TEST_MODE", "false").lower() == "true"


@router.get("/status", response_model=StreakStatusResponse)
async def get_streak_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Get the user's current streak status."""
    svc = StreakService(db)
    data = await svc.get_streak_status(current_user.id)
    await db.commit()

    claimable = None
    if data["claimable_reward"]:
        claimable = StreakClaimableReward(**data["claimable_reward"])

    return StreakStatusResponse(
        week_count=data["week_count"],
        streak_level=data["streak_level"],
        current_cycle=[StreakCycleEntry(**e) for e in data["current_cycle"]],
        claimable_reward=claimable,
        is_at_risk=data["is_at_risk"],
    )


@router.post("/claim", response_model=StreakClaimResponse)
async def claim_streak_reward(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Claim the current claimable streak reward."""
    svc = StreakService(db)
    result = await svc.claim_reward(current_user.id)
    await db.commit()

    if not result["success"]:
        raise HTTPException(status_code=404, detail="No claimable streak reward found")

    return StreakClaimResponse(
        success=result["success"],
        reward_type=result["reward_type"],
        spins_credited=result["spins_credited"],
        spin_type=result["spin_type"],
        points_credited=result["points_credited"],
        new_points_balance=result["new_points_balance"],
        new_standard_spins=result["new_standard_spins"],
        new_premium_spins=result["new_premium_spins"],
        new_spins_available=result["new_standard_spins"] + result["new_premium_spins"],
    )


# ── Test endpoints ─────────────────────────────────────────────────────────


@router.post("/test/advance")
async def test_advance_streak(
    amount: float = Query(100.0, description="Simulated receipt amount"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Test mode: simulate a qualifying receipt to advance the streak by 1 week."""
    if not TEST_MODE:
        raise HTTPException(status_code=403, detail="Test mode is not enabled")
    svc = StreakService(db)
    await svc.record_qualifying_receipt(current_user.id, amount, force=True)
    await db.commit()
    data = await svc.get_streak_status(current_user.id)
    return data


@router.post("/test/set-week")
async def test_set_week(
    week: int = Query(..., ge=0, description="Week number to set"),
    streak_level: int = Query(1, ge=1, le=2, description="Streak level (1 or 2)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Test mode: set streak to a specific week and level."""
    if not TEST_MODE:
        raise HTTPException(status_code=403, detail="Test mode is not enabled")
    svc = StreakService(db)
    await svc.test_set_week(current_user.id, week, streak_level)
    await db.commit()
    data = await svc.get_streak_status(current_user.id)
    return data


@router.post("/test/reset")
async def test_reset_streak(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Test mode: reset streak to 0."""
    if not TEST_MODE:
        raise HTTPException(status_code=403, detail="Test mode is not enabled")
    svc = StreakService(db)
    count = await svc.test_reset(current_user.id)
    await db.commit()
    data = await svc.get_streak_status(current_user.id)
    return data

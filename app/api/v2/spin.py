from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.models.enums import SpinType
from app.services.spin_service import SpinService
from app.schemas.spin import (
    SpinRequest,
    SpinResultResponse,
    SpinWheelConfigResponse,
    SpinSegmentResponse,
    SpinHistoryResponse,
)

router = APIRouter()


@router.get("/config", response_model=SpinWheelConfigResponse)
async def get_wheel_config(
    spin_type: str = "standard",
    current_user: User = Depends(get_current_db_user),
):
    """Get the wheel segment configuration for rendering."""
    stype = SpinType.PREMIUM if spin_type == "premium" else SpinType.STANDARD
    segments = SpinService.get_wheel_config(stype)
    return SpinWheelConfigResponse(
        segments=[SpinSegmentResponse(**s) for s in segments],
        total_segments=len(segments),
        spin_type=spin_type,
    )


@router.post("/spin", response_model=SpinResultResponse)
async def spin_wheel(
    body: SpinRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Spin the prize wheel. The outcome is determined server-side.
    The frontend uses the returned segment_index for animation.
    """
    svc = SpinService(db)
    spin_type = SpinType.PREMIUM if body.spin_type == "premium" else SpinType.STANDARD

    try:
        outcome, points_balance, std_spins, prem_spins = await svc.execute_spin(
            user_id=current_user.id,
            spin_type=spin_type,
            is_respin=body.is_respin,
            force_segment=body.force_segment,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await db.commit()

    return SpinResultResponse(
        segment_index=outcome.segment.index,
        segment_label=outcome.segment.label,
        segment_type=outcome.segment.segment_type,
        points_value=outcome.points_value,
        is_jackpot=outcome.segment.is_jackpot,
        mystery_reveal_value=outcome.mystery_reveal_value,
        grants_free_spin=outcome.grants_free_spin,
        spin_type=spin_type.value,
        new_points_balance=points_balance,
        standard_spins_remaining=std_spins,
        premium_spins_remaining=prem_spins,
        cash_value=round(outcome.points_value / 1000, 4),
        new_balance=round(points_balance / 1000, 4),
        spins_remaining=std_spins + prem_spins,
    )


@router.get("/history", response_model=list[SpinHistoryResponse])
async def get_spin_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Get recent spin history for the current user."""
    from app.db.repositories.spin_repo import SpinRepository
    repo = SpinRepository(db)
    spins = await repo.get_user_spin_history(current_user.id)
    return [
        SpinHistoryResponse(
            segment_label=s.segment_label,
            segment_type=s.segment_type,
            points_value=s.points_value,
            is_jackpot=s.is_jackpot,
            spin_type=s.spin_type.value if s.spin_type else "standard",
            created_at=s.created_at,
            cash_value=s.cash_value,
        )
        for s in spins
    ]

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
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
    current_user: User = Depends(get_current_db_user),
):
    """Get the wheel segment configuration for rendering."""
    segments = SpinService.get_wheel_config()
    return SpinWheelConfigResponse(
        segments=[SpinSegmentResponse(**s) for s in segments],
        total_segments=len(segments),
    )


@router.post("/spin", response_model=SpinResultResponse)
async def spin_wheel(
    body: SpinRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Spin the prize wheel. The outcome is determined server-side.
    The frontend should only use the returned segment_index for animation.
    """
    svc = SpinService(db)
    outcome, new_balance, spins_delta = await svc.execute_spin(
        user_id=current_user.id,
        has_double_next=body.has_double_next,
        force_segment=body.force_segment,
    )

    return SpinResultResponse(
        segment_index=outcome.segment.index,
        segment_label=outcome.segment.label,
        segment_type=outcome.segment.segment_type,
        cash_value=outcome.cash_value,
        is_jackpot=outcome.segment.is_jackpot,
        is_doubled=outcome.is_doubled,
        mystery_reveal_value=outcome.mystery_reveal_value,
        grants_free_spin=outcome.grants_free_spin,
        grants_double_next=outcome.grants_double_next,
        new_balance=new_balance,
        spins_remaining=spins_delta,
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
            cash_value=s.cash_value,
            is_jackpot=s.is_jackpot,
            is_doubled=s.is_doubled,
            created_at=s.created_at,
        )
        for s in spins
    ]

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.security import get_current_user, FirebaseUser
from app.schemas.rate_limit import RateLimitStatusResponse
from app.services.rate_limit_service import RateLimitService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/", response_model=RateLimitStatusResponse)
async def get_rate_limit_status(
    db: AsyncSession = Depends(get_db),
    current_user: FirebaseUser = Depends(get_current_user),
):
    """
    Get the current rate limit status for the authenticated user.

    Returns information about:
    - Messages used in the current period
    - Messages remaining
    - When the rate limit period resets
    """
    rate_limit_service = RateLimitService(db)
    status = await rate_limit_service.get_status(current_user.uid)

    return RateLimitStatusResponse(
        messages_used=status.messages_used,
        messages_limit=status.messages_limit,
        messages_remaining=status.messages_remaining,
        period_start_date=status.period_start_date,
        period_end_date=status.period_end_date,
        days_until_reset=status.days_until_reset,
    )

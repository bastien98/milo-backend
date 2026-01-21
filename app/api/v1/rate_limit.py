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
    - Receipt uploads used in the current period
    - Receipt uploads remaining
    - When the rate limit period resets
    """
    rate_limit_service = RateLimitService(db)
    message_status = await rate_limit_service.get_status(current_user.uid)
    receipt_status = await rate_limit_service.get_receipt_status(current_user.uid)

    return RateLimitStatusResponse(
        messages_used=message_status.messages_used,
        messages_limit=message_status.messages_limit,
        messages_remaining=message_status.messages_remaining,
        receipts_used=receipt_status.receipts_used,
        receipts_limit=receipt_status.receipts_limit,
        receipts_remaining=receipt_status.receipts_remaining,
        period_start_date=message_status.period_start_date,
        period_end_date=message_status.period_end_date,
        days_until_reset=message_status.days_until_reset,
    )

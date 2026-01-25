import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.schemas.analytics import PeriodsResponse
from app.services.analytics_service import AnalyticsService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/periods", response_model=PeriodsResponse)
async def get_periods(
    period_type: str = Query("month", description="Period type: week, month, year"),
    num_periods: int = Query(52, ge=1, le=52, description="Maximum number of periods to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Get lightweight metadata for all periods with data.

    This is an optimized endpoint that returns basic stats for each period
    using a single database query. It allows the frontend to:
    1. Display the period selector immediately
    2. Show basic stats (total spend, store count) for each period
    3. Load detailed data only for the currently selected period

    Only returns periods that have actual data (total_spend > 0).
    Periods are sorted by most recent first.
    """
    logger.info(
        f"Periods metadata request: user_id={current_user.id}, "
        f"period_type={period_type}, num_periods={num_periods}"
    )

    analytics = AnalyticsService(db)
    result = await analytics.get_periods_metadata(
        user_id=current_user.id,
        period_type=period_type,
        num_periods=num_periods,
    )

    logger.info(
        f"Periods metadata result: user_id={current_user.id}, "
        f"total_periods={result.total_periods}"
    )

    return result

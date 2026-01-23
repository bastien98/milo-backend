import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.schemas.analytics import (
    PeriodSummary,
    CategoryBreakdown,
    StoreBreakdown,
    TrendsResponse,
)
from app.services.analytics_service import AnalyticsService

logger = logging.getLogger(__name__)

router = APIRouter()


def get_period_dates(
    period: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> tuple[date, date]:
    """Calculate start and end dates for a period."""
    today = date.today()

    if start_date and end_date:
        return start_date, end_date

    if period == "week":
        # Current week (Monday to Sunday)
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    elif period == "month":
        # Current month
        start = today.replace(day=1)
        # End of month
        if today.month == 12:
            end = date(today.year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(today.year, today.month + 1, 1) - timedelta(days=1)
    elif period == "year":
        # Current year
        start = date(today.year, 1, 1)
        end = date(today.year, 12, 31)
    else:
        # Default to current month
        start = today.replace(day=1)
        if today.month == 12:
            end = date(today.year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(today.year, today.month + 1, 1) - timedelta(days=1)

    return start, end


@router.get("/summary", response_model=PeriodSummary)
async def get_summary(
    period: str = Query("month", description="Period: week, month, year, or custom"),
    start_date: Optional[date] = Query(None, description="Start date for custom period"),
    end_date: Optional[date] = Query(None, description="End date for custom period"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Get spending summary for a period with store breakdown.

    Shows total spending, transaction count, and per-store breakdown
    with visit counts and percentages.
    """
    start, end = get_period_dates(period, start_date, end_date)

    logger.info(
        f"Analytics summary request: user_id={current_user.id}, "
        f"period={period}, start_date={start}, end_date={end}"
    )

    analytics = AnalyticsService(db)
    result = await analytics.get_period_summary(
        user_id=current_user.id,
        start_date=start,
        end_date=end,
    )

    logger.info(
        f"Analytics summary result: user_id={current_user.id}, "
        f"transaction_count={result.transaction_count}, total_spend={result.total_spend}"
    )

    return result


@router.get("/categories", response_model=CategoryBreakdown)
async def get_categories(
    period: str = Query("month", description="Period: week, month, year, or custom"),
    start_date: Optional[date] = Query(None, description="Start date for custom period"),
    end_date: Optional[date] = Query(None, description="End date for custom period"),
    store_name: Optional[str] = Query(None, description="Filter by store"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Get spending breakdown by category.

    Shows how spending is distributed across the 16 categories.
    Optionally filter by store.
    """
    start, end = get_period_dates(period, start_date, end_date)

    analytics = AnalyticsService(db)
    return await analytics.get_category_breakdown(
        user_id=current_user.id,
        start_date=start,
        end_date=end,
        store_name=store_name,
    )


@router.get("/stores/{store_name}", response_model=StoreBreakdown)
async def get_store_breakdown(
    store_name: str,
    period: str = Query("month", description="Period: week, month, year, or custom"),
    start_date: Optional[date] = Query(None, description="Start date for custom period"),
    end_date: Optional[date] = Query(None, description="End date for custom period"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Get detailed breakdown for a specific store.

    Shows total spending, visit count, and category breakdown
    for the specified store.
    """
    start, end = get_period_dates(period, start_date, end_date)

    analytics = AnalyticsService(db)
    return await analytics.get_store_breakdown(
        user_id=current_user.id,
        store_name=store_name,
        start_date=start,
        end_date=end,
    )


@router.get("/trends", response_model=TrendsResponse)
async def get_trends(
    period_type: str = Query("month", description="Period type: week, month, year"),
    num_periods: int = Query(12, ge=1, le=52, description="Number of periods to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Get spending trends over time.

    Returns historical spending data for the specified number of periods.
    Useful for visualizing spending patterns over time.
    """
    analytics = AnalyticsService(db)
    return await analytics.get_spending_trends(
        user_id=current_user.id,
        period_type=period_type,
        num_periods=num_periods,
    )

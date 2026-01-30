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
    AggregateResponse,
    AllTimeResponse,
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
    logger.info(
        f"Analytics summary raw params: period={period}, "
        f"start_date={start_date} (type={type(start_date).__name__ if start_date else 'None'}), "
        f"end_date={end_date} (type={type(end_date).__name__ if end_date else 'None'})"
    )

    start, end = get_period_dates(period, start_date, end_date)

    logger.info(
        f"Analytics summary request: user_id={current_user.id}, "
        f"period={period}, computed_start={start}, computed_end={end}"
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


@router.get(
    "/stores/{store_name}/trends",
    response_model=TrendsResponse,
    summary="Get spending trends for a specific store",
    description="Returns spending trends filtered for a specific store over multiple time periods. "
    "Only periods with actual transactions are included (no empty periods). "
    "The total_spend, transaction_count, and average_health_score only include transactions from the specified store.",
)
async def get_store_trends(
    store_name: str,
    period_type: str = Query("month", description="Period type: week, month, year"),
    num_periods: int = Query(6, ge=1, le=52, description="Maximum number of periods to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Get spending trends for a specific store.

    Returns historical spending data for the specified store over multiple time periods.
    Useful for visualizing spending patterns at a particular store over time.

    Only periods with actual transactions are returned - periods with no transactions
    for this store are excluded. Results are sorted oldest first for chart display.
    The num_periods parameter acts as a maximum limit, not an exact count.

    Returns an empty trends array if the store doesn't exist or has no transactions.
    """
    analytics = AnalyticsService(db)
    return await analytics.get_store_spending_trends(
        user_id=current_user.id,
        store_name=store_name,
        period_type=period_type,
        num_periods=num_periods,
    )


@router.get(
    "/trends",
    response_model=TrendsResponse,
    summary="Get spending trends over time",
    description="Returns spending trends over multiple time periods. "
    "Only periods with actual transactions are included (no empty periods).",
)
async def get_trends(
    period_type: str = Query("month", description="Period type: week, month, year"),
    num_periods: int = Query(12, ge=1, le=52, description="Maximum number of periods to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Get spending trends over time.

    Returns historical spending data for the user over multiple time periods.
    Useful for visualizing spending patterns over time.

    Only periods with actual transactions are returned - empty periods are excluded.
    For example, if a user has transactions in January and March but not February,
    only January and March will be returned. Results are sorted oldest first for
    chart display. The num_periods parameter acts as a maximum limit, not an exact count.
    """
    analytics = AnalyticsService(db)
    return await analytics.get_spending_trends(
        user_id=current_user.id,
        period_type=period_type,
        num_periods=num_periods,
    )


@router.get(
    "/aggregate",
    response_model=AggregateResponse,
    summary="Get aggregate statistics across multiple periods",
    description="Returns aggregate statistics including totals, averages, extremes, "
    "top categories, top stores, and health score distribution across multiple time periods.",
)
async def get_aggregate(
    period_type: str = Query("month", description="Period granularity: week, month, year"),
    num_periods: int = Query(12, ge=1, le=52, description="Number of periods to aggregate"),
    start_date: Optional[date] = Query(None, description="Optional start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="Optional end date (YYYY-MM-DD)"),
    all_time: bool = Query(False, description="If true, return all-time stats (ignores date filters)"),
    top_categories_limit: int = Query(5, ge=1, le=20, description="Number of top categories to return"),
    top_stores_limit: int = Query(5, ge=1, le=20, description="Number of top stores to return"),
    min_category_percentage: float = Query(0, ge=0, le=100, description="Minimum percentage threshold for categories"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Get aggregate statistics across multiple periods.

    Returns comprehensive aggregate data including:
    - **totals**: Total spend, transactions, receipts, and items
    - **averages**: Average spend per period, transaction value, item price, health score, etc.
    - **extremes**: Max/min spending periods and highest/lowest health score periods
    - **top_categories**: Top spending categories with percentages and health scores
    - **top_stores**: Top stores by amount spent with visit counts
    - **health_score_distribution**: Distribution of health scores across all transactions

    Use `all_time=true` to get statistics across the entire user history.
    Use `start_date` and `end_date` for custom date ranges.
    """
    logger.info(
        f"Aggregate request: user_id={current_user.id}, period_type={period_type}, "
        f"num_periods={num_periods}, all_time={all_time}"
    )

    analytics = AnalyticsService(db)
    return await analytics.get_aggregate_stats(
        user_id=current_user.id,
        period_type=period_type,
        num_periods=num_periods,
        start_date=start_date,
        end_date=end_date,
        all_time=all_time,
        top_categories_limit=top_categories_limit,
        top_stores_limit=top_stores_limit,
        min_category_percentage=min_category_percentage,
    )


@router.get(
    "/all-time",
    response_model=AllTimeResponse,
    summary="Get all-time statistics",
    description="Returns all-time statistics for the user including total receipts, items, "
    "spend, top stores by visits and spend, and date range.",
)
async def get_all_time(
    top_stores_limit: int = Query(3, ge=1, le=10, description="Number of top stores to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Get all-time statistics for the user.

    Returns comprehensive all-time data including:
    - Total receipts, items, spend, and transactions
    - Average item price and health score
    - Top stores by visit count (with ranks)
    - Top stores by total spend (with ranks)
    - First and last receipt dates

    This endpoint is optimized for the scan view hero cards on the frontend.
    """
    logger.info(f"All-time request: user_id={current_user.id}, top_stores_limit={top_stores_limit}")

    analytics = AnalyticsService(db)
    return await analytics.get_all_time_stats(
        user_id=current_user.id,
        top_stores_limit=top_stores_limit,
    )

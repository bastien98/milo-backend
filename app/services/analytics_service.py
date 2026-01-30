import logging
from datetime import date, timedelta
from typing import Optional
from collections import defaultdict

from sqlalchemy import select, and_, func, case, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.schemas.analytics import (
    PeriodSummary,
    StoreSpending,
    CategoryBreakdown,
    CategorySpending,
    StoreBreakdown,
    SpendingTrend,
    TrendsResponse,
    PeriodMetadata,
    PeriodsResponse,
    AggregateTotals,
    AggregateAverages,
    PeriodExtreme,
    HealthScoreExtreme,
    AggregateExtremes,
    HealthScoreDistribution,
    AggregateResponse,
    StoreByVisits,
    StoreBySpend,
    AllTimeResponse,
)

logger = logging.getLogger(__name__)


class AnalyticsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_period_summary(
        self,
        user_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        all_time: bool = False,
    ) -> PeriodSummary:
        """Get spending summary for a period with store breakdown.

        Args:
            user_id: The user's ID
            start_date: Start date for the period (None if all_time)
            end_date: End date for the period (None if all_time)
            all_time: If True, query all transactions regardless of date
        """
        logger.info(
            f"Analytics query: user_id={user_id}, start_date={start_date}, "
            f"end_date={end_date}, all_time={all_time}"
        )

        # Build query based on whether this is an all-time query
        if all_time:
            query = select(Transaction).where(Transaction.user_id == user_id)
        else:
            query = select(Transaction).where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= start_date,
                    Transaction.date <= end_date,
                )
            )

        result = await self.db.execute(query)
        transactions = list(result.scalars().all())

        # For all-time queries, compute actual date range from transactions
        if all_time and transactions:
            dates = [t.date for t in transactions]
            actual_start = min(dates)
            actual_end = max(dates)
        elif all_time:
            # No transactions - use today
            actual_start = date.today()
            actual_end = date.today()
        else:
            actual_start = start_date
            actual_end = end_date

        logger.info(
            f"Analytics found {len(transactions)} transactions for user_id={user_id} "
            f"{'(all time)' if all_time else f'in date range {actual_start} to {actual_end}'}"
        )
        if transactions:
            dates = [t.date for t in transactions]
            unique_receipt_ids = set(t.receipt_id for t in transactions if t.receipt_id)
            logger.debug(
                f"Transaction dates: min={min(dates)}, max={max(dates)}, "
                f"unique_receipts={len(unique_receipt_ids)}"
            )

        # Calculate totals (item_price already represents the line total from receipt)
        total_spend = sum(t.item_price for t in transactions)
        transaction_count = len(transactions)

        # Calculate average health score (only for items with health scores)
        health_scores = [t.health_score for t in transactions if t.health_score is not None]
        average_health_score = round(sum(health_scores) / len(health_scores), 2) if health_scores else None

        # Group by store (including health scores for per-store average)
        store_data = defaultdict(lambda: {"amount": 0.0, "receipt_ids": set(), "health_scores": []})
        for t in transactions:
            store_data[t.store_name]["amount"] += t.item_price
            if t.receipt_id:
                store_data[t.store_name]["receipt_ids"].add(t.receipt_id)
            if t.health_score is not None:
                store_data[t.store_name]["health_scores"].append(t.health_score)

        # Build store spending list
        stores = []
        for store_name, data in store_data.items():
            percentage = (data["amount"] / total_spend * 100) if total_spend > 0 else 0
            visit_count = len(data["receipt_ids"])
            store_avg_health = (
                round(sum(data["health_scores"]) / len(data["health_scores"]), 2)
                if data["health_scores"]
                else None
            )
            logger.debug(
                f"Store '{store_name}': visits={visit_count}, receipt_ids={data['receipt_ids']}"
            )
            stores.append(
                StoreSpending(
                    store_name=store_name,
                    amount_spent=round(data["amount"], 2),
                    store_visits=visit_count,
                    percentage=round(percentage, 1),
                    average_health_score=store_avg_health,
                )
            )

        # Sort by amount spent descending
        stores.sort(key=lambda x: x.amount_spent, reverse=True)

        # Format period string
        period_str = "All Time" if all_time else self._format_period(actual_start, actual_end)

        return PeriodSummary(
            period=period_str,
            start_date=actual_start,
            end_date=actual_end,
            total_spend=round(total_spend, 2),
            transaction_count=transaction_count,
            stores=stores,
            average_health_score=average_health_score,
        )

    async def get_category_breakdown(
        self,
        user_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        store_name: Optional[str] = None,
        all_time: bool = False,
    ) -> CategoryBreakdown:
        """Get spending breakdown by category for a period.

        Args:
            user_id: The user's ID
            start_date: Start date for the period (None if all_time)
            end_date: End date for the period (None if all_time)
            store_name: Optional store filter
            all_time: If True, query all transactions regardless of date
        """
        # Build conditions
        conditions = [Transaction.user_id == user_id]

        if not all_time:
            conditions.append(Transaction.date >= start_date)
            conditions.append(Transaction.date <= end_date)

        if store_name:
            conditions.append(Transaction.store_name == store_name)

        # Get all transactions
        result = await self.db.execute(
            select(Transaction).where(and_(*conditions))
        )
        transactions = list(result.scalars().all())

        # For all-time queries, compute actual date range from transactions
        if all_time and transactions:
            dates = [t.date for t in transactions]
            actual_start = min(dates)
            actual_end = max(dates)
        elif all_time:
            actual_start = date.today()
            actual_end = date.today()
        else:
            actual_start = start_date
            actual_end = end_date

        # Calculate totals (item_price already represents the line total from receipt)
        total_spend = sum(t.item_price for t in transactions)

        # Calculate overall average health score
        all_health_scores = [t.health_score for t in transactions if t.health_score is not None]
        overall_avg_health = round(sum(all_health_scores) / len(all_health_scores), 2) if all_health_scores else None

        # Group by category
        category_data = defaultdict(lambda: {"amount": 0.0, "count": 0, "health_scores": []})
        for t in transactions:
            category_data[t.category.value]["amount"] += t.item_price
            category_data[t.category.value]["count"] += 1
            if t.health_score is not None:
                category_data[t.category.value]["health_scores"].append(t.health_score)

        # Build category spending list
        categories = []
        for category_name, data in category_data.items():
            percentage = (data["amount"] / total_spend * 100) if total_spend > 0 else 0
            avg_health = (
                round(sum(data["health_scores"]) / len(data["health_scores"]), 2)
                if data["health_scores"]
                else None
            )
            categories.append(
                CategorySpending(
                    name=category_name,
                    spent=round(data["amount"], 2),
                    percentage=round(percentage, 1),
                    transaction_count=data["count"],
                    average_health_score=avg_health,
                )
            )

        # Sort by spent descending
        categories.sort(key=lambda x: x.spent, reverse=True)

        # Format period string
        period_str = "All Time" if all_time else self._format_period(actual_start, actual_end)

        return CategoryBreakdown(
            period=period_str,
            start_date=actual_start,
            end_date=actual_end,
            total_spend=round(total_spend, 2),
            categories=categories,
            average_health_score=overall_avg_health,
        )

    async def get_store_breakdown(
        self,
        user_id: str,
        store_name: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        all_time: bool = False,
    ) -> StoreBreakdown:
        """Get detailed breakdown for a specific store.

        Args:
            user_id: The user's ID
            store_name: The store to get breakdown for
            start_date: Start date for the period (None if all_time)
            end_date: End date for the period (None if all_time)
            all_time: If True, query all transactions regardless of date
        """
        # Build conditions
        conditions = [
            Transaction.user_id == user_id,
            Transaction.store_name == store_name,
        ]

        if not all_time:
            conditions.append(Transaction.date >= start_date)
            conditions.append(Transaction.date <= end_date)

        # Get all transactions for store
        result = await self.db.execute(
            select(Transaction).where(and_(*conditions))
        )
        transactions = list(result.scalars().all())

        # For all-time queries, compute actual date range from transactions
        if all_time and transactions:
            dates = [t.date for t in transactions]
            actual_start = min(dates)
            actual_end = max(dates)
        elif all_time:
            actual_start = date.today()
            actual_end = date.today()
        else:
            actual_start = start_date
            actual_end = end_date

        # Calculate totals (item_price already represents the line total from receipt)
        total_spend = sum(t.item_price for t in transactions)
        total_items = sum(t.quantity for t in transactions)
        receipt_ids = set(t.receipt_id for t in transactions if t.receipt_id)

        # Calculate average health score for this store
        store_health_scores = [t.health_score for t in transactions if t.health_score is not None]
        store_avg_health = round(sum(store_health_scores) / len(store_health_scores), 2) if store_health_scores else None

        # Calculate average item price
        average_item_price = round(total_spend / total_items, 2) if total_items > 0 else None

        # Group by category
        category_data = defaultdict(lambda: {"amount": 0.0, "count": 0, "health_scores": []})
        for t in transactions:
            category_data[t.category.value]["amount"] += t.item_price
            category_data[t.category.value]["count"] += 1
            if t.health_score is not None:
                category_data[t.category.value]["health_scores"].append(t.health_score)

        # Build category spending list
        categories = []
        for category_name, data in category_data.items():
            percentage = (data["amount"] / total_spend * 100) if total_spend > 0 else 0
            avg_health = (
                round(sum(data["health_scores"]) / len(data["health_scores"]), 2)
                if data["health_scores"]
                else None
            )
            categories.append(
                CategorySpending(
                    name=category_name,
                    spent=round(data["amount"], 2),
                    percentage=round(percentage, 1),
                    transaction_count=data["count"],
                    average_health_score=avg_health,
                )
            )

        # Sort by spent descending
        categories.sort(key=lambda x: x.spent, reverse=True)

        # Format period string
        period_str = "All Time" if all_time else self._format_period(actual_start, actual_end)

        return StoreBreakdown(
            store_name=store_name,
            period=period_str,
            start_date=actual_start,
            end_date=actual_end,
            total_store_spend=round(total_spend, 2),
            store_visits=len(receipt_ids),
            categories=categories,
            average_health_score=store_avg_health,
            total_items=total_items,
            average_item_price=average_item_price,
        )

    async def get_spending_trends(
        self,
        user_id: str,
        period_type: str,  # "week", "month", "year"
        num_periods: int = 12,
    ) -> TrendsResponse:
        """
        Get spending trends over time.

        Only returns periods that have actual transactions (no empty periods).
        """
        today = date.today()

        # Calculate the earliest date we should look back to
        if period_type == "week":
            earliest_start = today - timedelta(weeks=num_periods)
            trunc_interval = 'week'
        elif period_type == "month":
            month = today.month - num_periods
            year = today.year
            while month <= 0:
                month += 12
                year -= 1
            earliest_start = date(year, month, 1)
            trunc_interval = 'month'
        else:  # year
            earliest_start = date(today.year - num_periods, 1, 1)
            trunc_interval = 'year'

        # Use GROUP BY to only get periods with data (single efficient query)
        period_start_col = func.date_trunc(trunc_interval, Transaction.date).label('period_start')

        query = (
            select(
                period_start_col,
                func.sum(Transaction.item_price).label('total_spend'),
                func.count().label('transaction_count'),
                func.avg(
                    case(
                        (Transaction.health_score.isnot(None), Transaction.health_score),
                        else_=None
                    )
                ).label('avg_health_score'),
            )
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= earliest_start,
                )
            )
            .group_by(period_start_col)
            .having(func.count() > 0)
            .order_by(period_start_col.asc())  # Oldest first for chart display
            .limit(num_periods)
        )

        result = await self.db.execute(query)
        rows = result.all()

        trends = []
        for row in rows:
            period_start_date = row.period_start.date() if hasattr(row.period_start, 'date') else row.period_start

            # Calculate period end date
            if period_type == "week":
                period_end_date = period_start_date + timedelta(days=6)
            elif period_type == "month":
                if period_start_date.month == 12:
                    period_end_date = date(period_start_date.year + 1, 1, 1) - timedelta(days=1)
                else:
                    period_end_date = date(period_start_date.year, period_start_date.month + 1, 1) - timedelta(days=1)
            else:  # year
                period_end_date = date(period_start_date.year, 12, 31)

            avg_health = round(float(row.avg_health_score), 2) if row.avg_health_score is not None else None

            trends.append(
                SpendingTrend(
                    period=self._format_period(period_start_date, period_end_date),
                    start_date=period_start_date,
                    end_date=period_end_date,
                    total_spend=round(float(row.total_spend), 2),
                    transaction_count=row.transaction_count,
                    average_health_score=avg_health,
                )
            )

        return TrendsResponse(
            trends=trends,
            period_type=period_type,
        )

    async def get_store_spending_trends(
        self,
        user_id: str,
        store_name: str,
        period_type: str,  # "week", "month", "year"
        num_periods: int = 6,
    ) -> TrendsResponse:
        """
        Get spending trends over time for a specific store.

        Only returns periods that have actual transactions (no empty periods).
        """
        today = date.today()

        # Calculate the earliest date we should look back to
        if period_type == "week":
            earliest_start = today - timedelta(weeks=num_periods)
            trunc_interval = 'week'
        elif period_type == "month":
            month = today.month - num_periods
            year = today.year
            while month <= 0:
                month += 12
                year -= 1
            earliest_start = date(year, month, 1)
            trunc_interval = 'month'
        else:  # year
            earliest_start = date(today.year - num_periods, 1, 1)
            trunc_interval = 'year'

        # Use GROUP BY to only get periods with data (single efficient query)
        period_start_col = func.date_trunc(trunc_interval, Transaction.date).label('period_start')

        query = (
            select(
                period_start_col,
                func.sum(Transaction.item_price).label('total_spend'),
                func.count().label('transaction_count'),
                func.avg(
                    case(
                        (Transaction.health_score.isnot(None), Transaction.health_score),
                        else_=None
                    )
                ).label('avg_health_score'),
            )
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.store_name == store_name,
                    Transaction.date >= earliest_start,
                )
            )
            .group_by(period_start_col)
            .having(func.count() > 0)
            .order_by(period_start_col.asc())  # Oldest first for chart display
            .limit(num_periods)
        )

        result = await self.db.execute(query)
        rows = result.all()

        trends = []
        for row in rows:
            period_start_date = row.period_start.date() if hasattr(row.period_start, 'date') else row.period_start

            # Calculate period end date
            if period_type == "week":
                period_end_date = period_start_date + timedelta(days=6)
            elif period_type == "month":
                if period_start_date.month == 12:
                    period_end_date = date(period_start_date.year + 1, 1, 1) - timedelta(days=1)
                else:
                    period_end_date = date(period_start_date.year, period_start_date.month + 1, 1) - timedelta(days=1)
            else:  # year
                period_end_date = date(period_start_date.year, 12, 31)

            avg_health = round(float(row.avg_health_score), 2) if row.avg_health_score is not None else None

            trends.append(
                SpendingTrend(
                    period=self._format_period(period_start_date, period_end_date),
                    start_date=period_start_date,
                    end_date=period_end_date,
                    total_spend=round(float(row.total_spend), 2),
                    transaction_count=row.transaction_count,
                    average_health_score=avg_health,
                )
            )

        return TrendsResponse(
            trends=trends,
            period_type=period_type,
        )

    async def get_periods_metadata(
        self,
        user_id: str,
        period_type: str = "month",  # "week", "month", "year"
        num_periods: int = 52,
    ) -> PeriodsResponse:
        """
        Get lightweight metadata for all periods with data.

        Uses a single optimized SQL query with GROUP BY for performance.
        Returns periods sorted by most recent first.
        """
        today = date.today()

        # Calculate the earliest date we should look back to
        if period_type == "week":
            earliest_start = today - timedelta(weeks=num_periods)
            trunc_interval = 'week'
        elif period_type == "month":
            # Go back num_periods months
            month = today.month - num_periods
            year = today.year
            while month <= 0:
                month += 12
                year -= 1
            earliest_start = date(year, month, 1)
            trunc_interval = 'month'
        else:  # year
            earliest_start = date(today.year - num_periods, 1, 1)
            trunc_interval = 'year'

        # Build the aggregation query using date_trunc for period grouping
        period_start_col = func.date_trunc(trunc_interval, Transaction.date).label('period_start')

        query = (
            select(
                period_start_col,
                func.sum(Transaction.item_price).label('total_spend'),
                func.count(func.distinct(Transaction.receipt_id)).label('receipt_count'),
                func.count(func.distinct(Transaction.store_name)).label('store_count'),
                func.count().label('transaction_count'),
                func.sum(Transaction.quantity).label('total_items'),
                func.avg(
                    case(
                        (Transaction.health_score.isnot(None), Transaction.health_score),
                        else_=None
                    )
                ).label('avg_health_score'),
            )
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= earliest_start,
                )
            )
            .group_by(period_start_col)
            .having(func.sum(Transaction.item_price) > 0)
            .order_by(period_start_col.desc())
            .limit(num_periods)
        )

        result = await self.db.execute(query)
        rows = result.all()

        periods = []
        for row in rows:
            period_start_date = row.period_start.date() if hasattr(row.period_start, 'date') else row.period_start

            # Calculate period end date
            if period_type == "week":
                period_end_date = period_start_date + timedelta(days=6)
            elif period_type == "month":
                if period_start_date.month == 12:
                    period_end_date = date(period_start_date.year + 1, 1, 1) - timedelta(days=1)
                else:
                    period_end_date = date(period_start_date.year, period_start_date.month + 1, 1) - timedelta(days=1)
            else:  # year
                period_end_date = date(period_start_date.year, 12, 31)

            avg_health = round(float(row.avg_health_score), 2) if row.avg_health_score is not None else None

            periods.append(
                PeriodMetadata(
                    period=self._format_period(period_start_date, period_end_date),
                    period_start=period_start_date,
                    period_end=period_end_date,
                    total_spend=round(float(row.total_spend), 2),
                    receipt_count=row.receipt_count,
                    store_count=row.store_count,
                    transaction_count=row.transaction_count,
                    total_items=row.total_items,
                    average_health_score=avg_health,
                )
            )

        return PeriodsResponse(
            periods=periods,
            total_periods=len(periods),
        )

    def _format_period(self, start_date: date, end_date: date) -> str:
        """Format a date range as a period string."""
        if start_date.year == end_date.year:
            if start_date.month == end_date.month:
                return start_date.strftime("%B %Y")
            else:
                return f"{start_date.strftime('%b')} - {end_date.strftime('%b %Y')}"
        else:
            return f"{start_date.strftime('%b %Y')} - {end_date.strftime('%b %Y')}"

    def _get_period_boundaries(
        self,
        period_type: str,
        num_periods: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> tuple[date, date]:
        """Calculate start and end dates for aggregate queries."""
        today = date.today()

        if start_date and end_date:
            return start_date, end_date

        # Calculate based on period type and num_periods
        if period_type == "week":
            # End at end of current week (Sunday)
            end = today + timedelta(days=(6 - today.weekday()))
            start = end - timedelta(weeks=num_periods) + timedelta(days=1)
        elif period_type == "month":
            # End at end of current month
            if today.month == 12:
                end = date(today.year + 1, 1, 1) - timedelta(days=1)
            else:
                end = date(today.year, today.month + 1, 1) - timedelta(days=1)
            # Go back num_periods months
            month = today.month - num_periods + 1
            year = today.year
            while month <= 0:
                month += 12
                year -= 1
            start = date(year, month, 1)
        else:  # year
            end = date(today.year, 12, 31)
            start = date(today.year - num_periods + 1, 1, 1)

        return start, end

    async def get_aggregate_stats(
        self,
        user_id: str,
        period_type: str = "month",
        num_periods: int = 12,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        all_time: bool = False,
        top_categories_limit: int = 5,
        top_stores_limit: int = 5,
        min_category_percentage: float = 0,
    ) -> AggregateResponse:
        """
        Get aggregate statistics across multiple periods.

        Args:
            user_id: The user's ID
            period_type: Period granularity (week, month, year)
            num_periods: Number of periods to aggregate
            start_date: Optional custom start date
            end_date: Optional custom end date
            all_time: If True, ignore date filters
            top_categories_limit: Number of top categories to return
            top_stores_limit: Number of top stores to return
            min_category_percentage: Minimum percentage threshold for categories
        """
        logger.info(
            f"Aggregate stats request: user_id={user_id}, period_type={period_type}, "
            f"num_periods={num_periods}, all_time={all_time}"
        )

        # Determine date range
        if all_time:
            # Get the full date range from user's first to last transaction
            date_range_query = select(
                func.min(Transaction.date).label('first_date'),
                func.max(Transaction.date).label('last_date'),
            ).where(Transaction.user_id == user_id)
            result = await self.db.execute(date_range_query)
            row = result.one_or_none()
            if row and row.first_date and row.last_date:
                query_start = row.first_date
                query_end = row.last_date
            else:
                # No transactions, return empty response
                today = date.today()
                return AggregateResponse(
                    period_type=period_type,
                    num_periods=num_periods,
                    start_date=today,
                    end_date=today,
                    totals=AggregateTotals(
                        total_spend=0, total_transactions=0, total_receipts=0, total_items=0
                    ),
                    averages=AggregateAverages(
                        average_spend_per_period=0, average_transaction_value=0,
                        average_item_price=0, average_health_score=None,
                        average_receipts_per_period=0, average_transactions_per_period=0,
                        average_items_per_receipt=0
                    ),
                    extremes=AggregateExtremes(),
                    top_categories=[],
                    top_stores=[],
                    health_score_distribution=HealthScoreDistribution(),
                )
        else:
            query_start, query_end = self._get_period_boundaries(
                period_type, num_periods, start_date, end_date
            )

        # Get all transactions in the range
        query = select(Transaction).where(
            and_(
                Transaction.user_id == user_id,
                Transaction.date >= query_start,
                Transaction.date <= query_end,
            )
        )
        result = await self.db.execute(query)
        transactions = list(result.scalars().all())

        if not transactions:
            return AggregateResponse(
                period_type=period_type,
                num_periods=num_periods,
                start_date=query_start,
                end_date=query_end,
                totals=AggregateTotals(
                    total_spend=0, total_transactions=0, total_receipts=0, total_items=0
                ),
                averages=AggregateAverages(
                    average_spend_per_period=0, average_transaction_value=0,
                    average_item_price=0, average_health_score=None,
                    average_receipts_per_period=0, average_transactions_per_period=0,
                    average_items_per_receipt=0
                ),
                extremes=AggregateExtremes(),
                top_categories=[],
                top_stores=[],
                health_score_distribution=HealthScoreDistribution(),
            )

        # Calculate totals
        total_spend = sum(t.item_price for t in transactions)
        total_transactions = len(transactions)
        total_items = sum(t.quantity for t in transactions)
        receipt_ids = set(t.receipt_id for t in transactions if t.receipt_id)
        total_receipts = len(receipt_ids)

        # Calculate averages
        health_scores = [t.health_score for t in transactions if t.health_score is not None]
        avg_health_score = round(sum(health_scores) / len(health_scores), 2) if health_scores else None

        # Calculate number of actual periods with data for accurate averages
        periods_with_data = await self._count_periods_with_data(
            user_id, period_type, query_start, query_end
        )
        actual_num_periods = max(periods_with_data, 1)

        totals = AggregateTotals(
            total_spend=round(total_spend, 2),
            total_transactions=total_transactions,
            total_receipts=total_receipts,
            total_items=total_items,
        )

        averages = AggregateAverages(
            average_spend_per_period=round(total_spend / actual_num_periods, 2),
            average_transaction_value=round(total_spend / total_transactions, 2) if total_transactions > 0 else 0,
            average_item_price=round(total_spend / total_items, 2) if total_items > 0 else 0,
            average_health_score=avg_health_score,
            average_receipts_per_period=round(total_receipts / actual_num_periods, 2),
            average_transactions_per_period=round(total_transactions / actual_num_periods, 2),
            average_items_per_receipt=round(total_items / total_receipts, 2) if total_receipts > 0 else 0,
        )

        # Calculate extremes (max/min spending periods)
        extremes = await self._get_period_extremes(user_id, period_type, query_start, query_end)

        # Calculate top categories
        top_categories = self._calculate_top_categories(
            transactions, total_spend, top_categories_limit, min_category_percentage
        )

        # Calculate top stores
        top_stores = self._calculate_top_stores(transactions, total_spend, top_stores_limit)

        # Calculate health score distribution
        health_distribution = self._calculate_health_distribution(transactions)

        return AggregateResponse(
            period_type=period_type,
            num_periods=actual_num_periods,
            start_date=query_start,
            end_date=query_end,
            totals=totals,
            averages=averages,
            extremes=extremes,
            top_categories=top_categories,
            top_stores=top_stores,
            health_score_distribution=health_distribution,
        )

    async def _count_periods_with_data(
        self,
        user_id: str,
        period_type: str,
        start_date: date,
        end_date: date,
    ) -> int:
        """Count the number of periods with transaction data."""
        if period_type == "week":
            trunc_interval = 'week'
        elif period_type == "month":
            trunc_interval = 'month'
        else:
            trunc_interval = 'year'

        period_col = func.date_trunc(trunc_interval, Transaction.date)
        query = (
            select(func.count(func.distinct(period_col)))
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= start_date,
                    Transaction.date <= end_date,
                )
            )
        )
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def _get_period_extremes(
        self,
        user_id: str,
        period_type: str,
        start_date: date,
        end_date: date,
    ) -> AggregateExtremes:
        """Calculate extreme values (max/min spend, highest/lowest health) per period."""
        if period_type == "week":
            trunc_interval = 'week'
        elif period_type == "month":
            trunc_interval = 'month'
        else:
            trunc_interval = 'year'

        period_col = func.date_trunc(trunc_interval, Transaction.date).label('period_start')

        # Get aggregates per period
        query = (
            select(
                period_col,
                func.sum(Transaction.item_price).label('total_spend'),
                func.avg(
                    case(
                        (Transaction.health_score.isnot(None), Transaction.health_score),
                        else_=None
                    )
                ).label('avg_health_score'),
            )
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= start_date,
                    Transaction.date <= end_date,
                )
            )
            .group_by(period_col)
        )
        result = await self.db.execute(query)
        rows = result.all()

        if not rows:
            return AggregateExtremes()

        max_spend_row = None
        min_spend_row = None
        max_health_row = None
        min_health_row = None

        for row in rows:
            if max_spend_row is None or row.total_spend > max_spend_row.total_spend:
                max_spend_row = row
            if min_spend_row is None or row.total_spend < min_spend_row.total_spend:
                min_spend_row = row
            if row.avg_health_score is not None:
                if max_health_row is None or row.avg_health_score > max_health_row.avg_health_score:
                    max_health_row = row
                if min_health_row is None or row.avg_health_score < min_health_row.avg_health_score:
                    min_health_row = row

        def get_period_end(period_start_date: date, p_type: str) -> date:
            if p_type == "week":
                return period_start_date + timedelta(days=6)
            elif p_type == "month":
                if period_start_date.month == 12:
                    return date(period_start_date.year + 1, 1, 1) - timedelta(days=1)
                else:
                    return date(period_start_date.year, period_start_date.month + 1, 1) - timedelta(days=1)
            else:  # year
                return date(period_start_date.year, 12, 31)

        max_spending_period = None
        min_spending_period = None
        highest_health_period = None
        lowest_health_period = None

        if max_spend_row:
            ps = max_spend_row.period_start.date() if hasattr(max_spend_row.period_start, 'date') else max_spend_row.period_start
            pe = get_period_end(ps, period_type)
            max_spending_period = PeriodExtreme(
                period=self._format_period(ps, pe),
                period_start=ps,
                period_end=pe,
                total_spend=round(float(max_spend_row.total_spend), 2),
            )

        if min_spend_row:
            ps = min_spend_row.period_start.date() if hasattr(min_spend_row.period_start, 'date') else min_spend_row.period_start
            pe = get_period_end(ps, period_type)
            min_spending_period = PeriodExtreme(
                period=self._format_period(ps, pe),
                period_start=ps,
                period_end=pe,
                total_spend=round(float(min_spend_row.total_spend), 2),
            )

        if max_health_row:
            ps = max_health_row.period_start.date() if hasattr(max_health_row.period_start, 'date') else max_health_row.period_start
            pe = get_period_end(ps, period_type)
            highest_health_period = HealthScoreExtreme(
                period=self._format_period(ps, pe),
                period_start=ps,
                period_end=pe,
                average_health_score=round(float(max_health_row.avg_health_score), 2),
            )

        if min_health_row:
            ps = min_health_row.period_start.date() if hasattr(min_health_row.period_start, 'date') else min_health_row.period_start
            pe = get_period_end(ps, period_type)
            lowest_health_period = HealthScoreExtreme(
                period=self._format_period(ps, pe),
                period_start=ps,
                period_end=pe,
                average_health_score=round(float(min_health_row.avg_health_score), 2),
            )

        return AggregateExtremes(
            max_spending_period=max_spending_period,
            min_spending_period=min_spending_period,
            highest_health_score_period=highest_health_period,
            lowest_health_score_period=lowest_health_period,
        )

    def _calculate_top_categories(
        self,
        transactions: list,
        total_spend: float,
        limit: int,
        min_percentage: float,
    ) -> list[CategorySpending]:
        """Calculate top categories from transactions."""
        category_data = defaultdict(lambda: {"amount": 0.0, "count": 0, "health_scores": []})

        for t in transactions:
            category_data[t.category.value]["amount"] += t.item_price
            category_data[t.category.value]["count"] += 1
            if t.health_score is not None:
                category_data[t.category.value]["health_scores"].append(t.health_score)

        categories = []
        for category_name, data in category_data.items():
            percentage = (data["amount"] / total_spend * 100) if total_spend > 0 else 0
            if percentage < min_percentage:
                continue
            avg_health = (
                round(sum(data["health_scores"]) / len(data["health_scores"]), 2)
                if data["health_scores"]
                else None
            )
            categories.append(
                CategorySpending(
                    name=category_name,
                    spent=round(data["amount"], 2),
                    percentage=round(percentage, 1),
                    transaction_count=data["count"],
                    average_health_score=avg_health,
                )
            )

        categories.sort(key=lambda x: x.spent, reverse=True)
        return categories[:limit]

    def _calculate_top_stores(
        self,
        transactions: list,
        total_spend: float,
        limit: int,
    ) -> list[StoreSpending]:
        """Calculate top stores from transactions."""
        store_data = defaultdict(lambda: {"amount": 0.0, "receipt_ids": set(), "health_scores": []})

        for t in transactions:
            store_data[t.store_name]["amount"] += t.item_price
            if t.receipt_id:
                store_data[t.store_name]["receipt_ids"].add(t.receipt_id)
            if t.health_score is not None:
                store_data[t.store_name]["health_scores"].append(t.health_score)

        stores = []
        for store_name, data in store_data.items():
            percentage = (data["amount"] / total_spend * 100) if total_spend > 0 else 0
            store_avg_health = (
                round(sum(data["health_scores"]) / len(data["health_scores"]), 2)
                if data["health_scores"]
                else None
            )
            stores.append(
                StoreSpending(
                    store_name=store_name,
                    amount_spent=round(data["amount"], 2),
                    store_visits=len(data["receipt_ids"]),
                    percentage=round(percentage, 1),
                    average_health_score=store_avg_health,
                )
            )

        stores.sort(key=lambda x: x.amount_spent, reverse=True)
        return stores[:limit]

    def _calculate_health_distribution(self, transactions: list) -> HealthScoreDistribution:
        """Calculate health score distribution from transactions."""
        distribution = {
            "score_1": 0,
            "score_2": 0,
            "score_3": 0,
            "score_4": 0,
            "score_5": 0,
            "unscored": 0,
        }

        for t in transactions:
            if t.health_score is None:
                distribution["unscored"] += 1
            elif t.health_score == 1:
                distribution["score_1"] += 1
            elif t.health_score == 2:
                distribution["score_2"] += 1
            elif t.health_score == 3:
                distribution["score_3"] += 1
            elif t.health_score == 4:
                distribution["score_4"] += 1
            elif t.health_score == 5:
                distribution["score_5"] += 1

        return HealthScoreDistribution(**distribution)

    async def get_all_time_stats(
        self,
        user_id: str,
        top_stores_limit: int = 3,
    ) -> AllTimeResponse:
        """
        Get all-time statistics for a user.

        Returns aggregate stats across all user transactions, including:
        - Total receipts, items, spend, transactions
        - Average item price and health score
        - Top stores by visits and spend
        - First and last receipt dates
        """
        logger.info(f"All-time stats request: user_id={user_id}, top_stores_limit={top_stores_limit}")

        # Get all transactions for the user
        query = select(Transaction).where(Transaction.user_id == user_id)
        result = await self.db.execute(query)
        transactions = list(result.scalars().all())

        if not transactions:
            return AllTimeResponse(
                total_receipts=0,
                total_items=0,
                total_spend=0,
                total_transactions=0,
                average_item_price=None,
                average_health_score=None,
                top_stores_by_visits=[],
                top_stores_by_spend=[],
                first_receipt_date=None,
                last_receipt_date=None,
            )

        # Calculate totals
        total_spend = sum(t.item_price for t in transactions)
        total_transactions = len(transactions)
        total_items = sum(t.quantity for t in transactions)
        receipt_ids = set(t.receipt_id for t in transactions if t.receipt_id)
        total_receipts = len(receipt_ids)

        # Calculate averages
        average_item_price = round(total_spend / total_items, 2) if total_items > 0 else None
        health_scores = [t.health_score for t in transactions if t.health_score is not None]
        average_health_score = round(sum(health_scores) / len(health_scores), 2) if health_scores else None

        # Calculate first and last receipt dates
        dates = [t.date for t in transactions]
        first_receipt_date = min(dates)
        last_receipt_date = max(dates)

        # Calculate top stores by visits
        store_visits = defaultdict(set)
        store_spend = defaultdict(float)
        for t in transactions:
            if t.receipt_id:
                store_visits[t.store_name].add(t.receipt_id)
            store_spend[t.store_name] += t.item_price

        # Top by visits
        stores_by_visits = [
            {"store_name": name, "visit_count": len(receipt_ids)}
            for name, receipt_ids in store_visits.items()
        ]
        stores_by_visits.sort(key=lambda x: x["visit_count"], reverse=True)
        top_stores_by_visits = [
            StoreByVisits(
                store_name=s["store_name"],
                visit_count=s["visit_count"],
                rank=i + 1,
            )
            for i, s in enumerate(stores_by_visits[:top_stores_limit])
        ]

        # Top by spend
        stores_by_spend_list = [
            {"store_name": name, "total_spent": spend}
            for name, spend in store_spend.items()
        ]
        stores_by_spend_list.sort(key=lambda x: x["total_spent"], reverse=True)
        top_stores_by_spend = [
            StoreBySpend(
                store_name=s["store_name"],
                total_spent=round(s["total_spent"], 2),
                rank=i + 1,
            )
            for i, s in enumerate(stores_by_spend_list[:top_stores_limit])
        ]

        return AllTimeResponse(
            total_receipts=total_receipts,
            total_items=total_items,
            total_spend=round(total_spend, 2),
            total_transactions=total_transactions,
            average_item_price=average_item_price,
            average_health_score=average_health_score,
            top_stores_by_visits=top_stores_by_visits,
            top_stores_by_spend=top_stores_by_spend,
            first_receipt_date=first_receipt_date,
            last_receipt_date=last_receipt_date,
        )

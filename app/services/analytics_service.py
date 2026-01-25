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
)

logger = logging.getLogger(__name__)


class AnalyticsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_period_summary(
        self,
        user_id: str,
        start_date: date,
        end_date: date,
    ) -> PeriodSummary:
        """Get spending summary for a period with store breakdown."""
        logger.info(
            f"Analytics query: user_id={user_id}, start_date={start_date} (type={type(start_date).__name__}), "
            f"end_date={end_date} (type={type(end_date).__name__})"
        )

        # Get all transactions in period
        query = select(Transaction).where(
            and_(
                Transaction.user_id == user_id,
                Transaction.date >= start_date,
                Transaction.date <= end_date,
            )
        )
        result = await self.db.execute(query)
        transactions = list(result.scalars().all())

        logger.info(
            f"Analytics found {len(transactions)} transactions for user_id={user_id} "
            f"in date range {start_date} to {end_date}"
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

        # Group by store
        store_data = defaultdict(lambda: {"amount": 0.0, "receipt_ids": set()})
        for t in transactions:
            store_data[t.store_name]["amount"] += t.item_price
            if t.receipt_id:
                store_data[t.store_name]["receipt_ids"].add(t.receipt_id)

        # Build store spending list
        stores = []
        for store_name, data in store_data.items():
            percentage = (data["amount"] / total_spend * 100) if total_spend > 0 else 0
            visit_count = len(data["receipt_ids"])
            logger.debug(
                f"Store '{store_name}': visits={visit_count}, receipt_ids={data['receipt_ids']}"
            )
            stores.append(
                StoreSpending(
                    store_name=store_name,
                    amount_spent=round(data["amount"], 2),
                    store_visits=visit_count,
                    percentage=round(percentage, 1),
                )
            )

        # Sort by amount spent descending
        stores.sort(key=lambda x: x.amount_spent, reverse=True)

        return PeriodSummary(
            period=self._format_period(start_date, end_date),
            start_date=start_date,
            end_date=end_date,
            total_spend=round(total_spend, 2),
            transaction_count=transaction_count,
            stores=stores,
            average_health_score=average_health_score,
        )

    async def get_category_breakdown(
        self,
        user_id: str,
        start_date: date,
        end_date: date,
        store_name: Optional[str] = None,
    ) -> CategoryBreakdown:
        """Get spending breakdown by category for a period."""
        # Build conditions
        conditions = [
            Transaction.user_id == user_id,
            Transaction.date >= start_date,
            Transaction.date <= end_date,
        ]
        if store_name:
            conditions.append(Transaction.store_name == store_name)

        # Get all transactions
        result = await self.db.execute(
            select(Transaction).where(and_(*conditions))
        )
        transactions = list(result.scalars().all())

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

        return CategoryBreakdown(
            period=self._format_period(start_date, end_date),
            start_date=start_date,
            end_date=end_date,
            total_spend=round(total_spend, 2),
            categories=categories,
            average_health_score=overall_avg_health,
        )

    async def get_store_breakdown(
        self,
        user_id: str,
        store_name: str,
        start_date: date,
        end_date: date,
    ) -> StoreBreakdown:
        """Get detailed breakdown for a specific store."""
        # Get all transactions for store
        result = await self.db.execute(
            select(Transaction).where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.store_name == store_name,
                    Transaction.date >= start_date,
                    Transaction.date <= end_date,
                )
            )
        )
        transactions = list(result.scalars().all())

        # Calculate totals (item_price already represents the line total from receipt)
        total_spend = sum(t.item_price for t in transactions)
        receipt_ids = set(t.receipt_id for t in transactions if t.receipt_id)

        # Calculate average health score for this store
        store_health_scores = [t.health_score for t in transactions if t.health_score is not None]
        store_avg_health = round(sum(store_health_scores) / len(store_health_scores), 2) if store_health_scores else None

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

        return StoreBreakdown(
            store_name=store_name,
            period=self._format_period(start_date, end_date),
            start_date=start_date,
            end_date=end_date,
            total_store_spend=round(total_spend, 2),
            store_visits=len(receipt_ids),
            categories=categories,
            average_health_score=store_avg_health,
        )

    async def get_spending_trends(
        self,
        user_id: str,
        period_type: str,  # "week", "month", "year"
        num_periods: int = 12,
    ) -> TrendsResponse:
        """Get spending trends over time."""
        trends = []
        today = date.today()

        for i in range(num_periods - 1, -1, -1):
            if period_type == "week":
                # Start of week (Monday)
                start = today - timedelta(days=today.weekday() + 7 * i)
                end = start + timedelta(days=6)
            elif period_type == "month":
                # Start of month
                month = today.month - i
                year = today.year
                while month <= 0:
                    month += 12
                    year -= 1
                start = date(year, month, 1)
                # End of month
                if month == 12:
                    end = date(year + 1, 1, 1) - timedelta(days=1)
                else:
                    end = date(year, month + 1, 1) - timedelta(days=1)
            else:  # year
                year = today.year - i
                start = date(year, 1, 1)
                end = date(year, 12, 31)

            # Get transactions for period
            result = await self.db.execute(
                select(Transaction).where(
                    and_(
                        Transaction.user_id == user_id,
                        Transaction.date >= start,
                        Transaction.date <= end,
                    )
                )
            )
            transactions = list(result.scalars().all())

            # Calculate totals (item_price already represents the line total from receipt)
            total_spend = sum(t.item_price for t in transactions)

            # Calculate average health score for this period
            period_health_scores = [t.health_score for t in transactions if t.health_score is not None]
            period_avg_health = round(sum(period_health_scores) / len(period_health_scores), 2) if period_health_scores else None

            trends.append(
                SpendingTrend(
                    period=self._format_period(start, end),
                    start_date=start,
                    end_date=end,
                    total_spend=round(total_spend, 2),
                    transaction_count=len(transactions),
                    average_health_score=period_avg_health,
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
        """Get spending trends over time for a specific store."""
        trends = []
        today = date.today()

        for i in range(num_periods - 1, -1, -1):
            if period_type == "week":
                # Start of week (Monday)
                start = today - timedelta(days=today.weekday() + 7 * i)
                end = start + timedelta(days=6)
            elif period_type == "month":
                # Start of month
                month = today.month - i
                year = today.year
                while month <= 0:
                    month += 12
                    year -= 1
                start = date(year, month, 1)
                # End of month
                if month == 12:
                    end = date(year + 1, 1, 1) - timedelta(days=1)
                else:
                    end = date(year, month + 1, 1) - timedelta(days=1)
            else:  # year
                year = today.year - i
                start = date(year, 1, 1)
                end = date(year, 12, 31)

            # Get transactions for period filtered by store
            result = await self.db.execute(
                select(Transaction).where(
                    and_(
                        Transaction.user_id == user_id,
                        Transaction.store_name == store_name,
                        Transaction.date >= start,
                        Transaction.date <= end,
                    )
                )
            )
            transactions = list(result.scalars().all())

            # Calculate totals
            total_spend = sum(t.item_price for t in transactions)

            # Calculate average health score for this period
            period_health_scores = [t.health_score for t in transactions if t.health_score is not None]
            period_avg_health = round(sum(period_health_scores) / len(period_health_scores), 2) if period_health_scores else None

            trends.append(
                SpendingTrend(
                    period=self._format_period(start, end),
                    start_date=start,
                    end_date=end,
                    total_spend=round(total_spend, 2),
                    transaction_count=len(transactions),
                    average_health_score=period_avg_health,
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

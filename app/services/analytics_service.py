from datetime import date, timedelta
from typing import List, Optional
from collections import defaultdict

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.models.enums import Category
from app.schemas.analytics import (
    PeriodSummary,
    StoreSpending,
    CategoryBreakdown,
    CategorySpending,
    StoreBreakdown,
    SpendingTrend,
    TrendsResponse,
)


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
        # Get all transactions in period
        result = await self.db.execute(
            select(Transaction).where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= start_date,
                    Transaction.date <= end_date,
                )
            )
        )
        transactions = list(result.scalars().all())

        # Calculate totals
        total_spend = sum(t.item_price for t in transactions)
        transaction_count = len(transactions)

        # Group by store
        store_data = defaultdict(lambda: {"amount": 0.0, "dates": set()})
        for t in transactions:
            store_data[t.store_name]["amount"] += t.item_price
            store_data[t.store_name]["dates"].add(t.date)

        # Build store spending list
        stores = []
        for store_name, data in store_data.items():
            percentage = (data["amount"] / total_spend * 100) if total_spend > 0 else 0
            stores.append(
                StoreSpending(
                    store_name=store_name,
                    amount_spent=round(data["amount"], 2),
                    store_visits=len(data["dates"]),
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

        # Calculate totals
        total_spend = sum(t.item_price for t in transactions)

        # Group by category
        category_data = defaultdict(lambda: {"amount": 0.0, "count": 0})
        for t in transactions:
            category_data[t.category.value]["amount"] += t.item_price
            category_data[t.category.value]["count"] += 1

        # Build category spending list
        categories = []
        for category_name, data in category_data.items():
            percentage = (data["amount"] / total_spend * 100) if total_spend > 0 else 0
            categories.append(
                CategorySpending(
                    name=category_name,
                    spent=round(data["amount"], 2),
                    percentage=round(percentage, 1),
                    transaction_count=data["count"],
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

        # Calculate totals
        total_spend = sum(t.item_price for t in transactions)
        visit_dates = set(t.date for t in transactions)

        # Group by category
        category_data = defaultdict(lambda: {"amount": 0.0, "count": 0})
        for t in transactions:
            category_data[t.category.value]["amount"] += t.item_price
            category_data[t.category.value]["count"] += 1

        # Build category spending list
        categories = []
        for category_name, data in category_data.items():
            percentage = (data["amount"] / total_spend * 100) if total_spend > 0 else 0
            categories.append(
                CategorySpending(
                    name=category_name,
                    spent=round(data["amount"], 2),
                    percentage=round(percentage, 1),
                    transaction_count=data["count"],
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
            store_visits=len(visit_dates),
            categories=categories,
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

            total_spend = sum(t.item_price for t in transactions)

            trends.append(
                SpendingTrend(
                    period=self._format_period(start, end),
                    start_date=start,
                    end_date=end,
                    total_spend=round(total_spend, 2),
                    transaction_count=len(transactions),
                )
            )

        return TrendsResponse(
            trends=trends,
            period_type=period_type,
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

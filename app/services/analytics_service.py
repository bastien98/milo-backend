from datetime import date, timedelta
from typing import Optional, Dict, List
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
    TopCategory,
    AllTimeResponse,
    YearStoreSpending,
    YearMonthlyBreakdown,
    YearCategorySpending,
    YearSummaryResponse,
    PieChartCategory,
    PieChartStore,
    PieChartSummaryResponse,
    get_category_color,
)
from app.services.category_registry import get_category_registry
from app.services.split_aware_calculation import SplitAwareCalculation


class AnalyticsService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.split_calc = SplitAwareCalculation(db)

    async def get_period_summary(
        self,
        user_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        all_time: bool = False,
    ) -> PeriodSummary:
        """Get spending summary for a period with store breakdown (split-adjusted).

        For transactions that are part of expense splits, only the user's
        portion is counted. For non-split transactions, the full amount is used.

        Args:
            user_id: The user's ID
            start_date: Start date for the period (None if all_time)
            end_date: End date for the period (None if all_time)
            all_time: If True, query all transactions regardless of date
        """

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

        if transactions:
            dates = [t.date for t in transactions]
            unique_receipt_ids = set(t.receipt_id for t in transactions if t.receipt_id)

        # Get split-adjusted amounts for all transactions
        tx_amounts = await self.split_calc.get_transaction_user_amounts(user_id, transactions)

        # Calculate totals (split-adjusted)
        total_spend = sum(amount for _, amount in tx_amounts)
        transaction_count = len(transactions)

        # Calculate average health score (only for items with health scores)
        health_scores = [t.health_score for t in transactions if t.health_score is not None]
        average_health_score = round(sum(health_scores) / len(health_scores), 2) if health_scores else None

        # Group by store (including health scores for per-store average)
        store_data = defaultdict(lambda: {"amount": 0.0, "receipt_ids": set(), "health_scores": []})
        for t, amount in tx_amounts:
            store_data[t.store_name]["amount"] += amount
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

    async def get_pie_chart_summary(
        self,
        user_id: str,
        month: int,
        year: int,
    ) -> PieChartSummaryResponse:
        """Get spending by category for a specific month/year (for Pie Chart, split-adjusted).

        For transactions that are part of expense splits, only the user's
        portion is counted. For non-split transactions, the full amount is used.

        Args:
            user_id: The user's ID
            month: Month (1-12)
            year: Year (e.g., 2026)

        Returns:
            PieChartSummaryResponse with categories containing total_spent and color_hex
        """
        import calendar

        # Calculate date range for the specified month
        start_date = date(year, month, 1)
        days_in_month = calendar.monthrange(year, month)[1]
        end_date = date(year, month, days_in_month)


        # Query transactions for the month
        query = select(Transaction).where(
            and_(
                Transaction.user_id == user_id,
                Transaction.date >= start_date,
                Transaction.date <= end_date,
            )
        )
        result = await self.db.execute(query)
        transactions = list(result.scalars().all())

        # Get split-adjusted amounts for all transactions
        tx_amounts = await self.split_calc.get_transaction_user_amounts(user_id, transactions)

        # Calculate total spend (split-adjusted)
        total_spend = sum(amount for _, amount in tx_amounts)

        # Group by category (split-adjusted)
        category_data = defaultdict(lambda: {"amount": 0.0, "count": 0, "health_scores": []})
        for t, amount in tx_amounts:
            category_data[t.category]["amount"] += amount
            category_data[t.category]["count"] += 1
            if t.health_score is not None:
                category_data[t.category]["health_scores"].append(t.health_score)

        # Build category list with color_hex
        registry = get_category_registry()
        categories = []
        for category_name, data in category_data.items():
            percentage = (data["amount"] / total_spend * 100) if total_spend > 0 else 0
            avg_health = (
                round(sum(data["health_scores"]) / len(data["health_scores"]), 2)
                if data["health_scores"]
                else None
            )
            # Get color from group-based color mapping
            color_hex = get_category_color(category_name)

            categories.append(
                PieChartCategory(
                    category_id=registry.get_category_id(category_name),
                    name=category_name,
                    total_spent=round(data["amount"], 2),
                    color_hex=color_hex,
                    percentage=round(percentage, 1),
                    transaction_count=data["count"],
                    average_health_score=avg_health,
                )
            )

        # Sort by total_spent descending
        categories.sort(key=lambda x: x.total_spent, reverse=True)

        # Group by store (split-adjusted)
        store_data = defaultdict(lambda: {"amount": 0.0, "receipts": set(), "health_scores": []})
        for t, amount in tx_amounts:
            store_data[t.store_name]["amount"] += amount
            store_data[t.store_name]["receipts"].add(t.receipt_id)
            if t.health_score is not None:
                store_data[t.store_name]["health_scores"].append(t.health_score)

        # Build store list
        stores = []
        for store_name, data in store_data.items():
            percentage = (data["amount"] / total_spend * 100) if total_spend > 0 else 0
            avg_health = (
                round(sum(data["health_scores"]) / len(data["health_scores"]), 2)
                if data["health_scores"]
                else None
            )

            stores.append(
                PieChartStore(
                    store_name=store_name,
                    total_spent=round(data["amount"], 2),
                    percentage=round(percentage, 1),
                    visit_count=len(data["receipts"]),
                    average_health_score=avg_health,
                )
            )

        # Sort by total_spent descending
        stores.sort(key=lambda x: x.total_spent, reverse=True)

        return PieChartSummaryResponse(
            month=month,
            year=year,
            total_spent=round(total_spend, 2),
            categories=categories,
            stores=stores,
        )

    async def get_category_breakdown(
        self,
        user_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        store_name: Optional[str] = None,
        all_time: bool = False,
    ) -> CategoryBreakdown:
        """Get spending breakdown by category for a period (split-adjusted).

        For transactions that are part of expense splits, only the user's
        portion is counted. For non-split transactions, the full amount is used.

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

        # Get split-adjusted amounts for all transactions
        tx_amounts = await self.split_calc.get_transaction_user_amounts(user_id, transactions)

        # Calculate totals (split-adjusted)
        total_spend = sum(amount for _, amount in tx_amounts)

        # Calculate overall average health score
        all_health_scores = [t.health_score for t in transactions if t.health_score is not None]
        overall_avg_health = round(sum(all_health_scores) / len(all_health_scores), 2) if all_health_scores else None

        # Group by category (split-adjusted)
        category_data = defaultdict(lambda: {"amount": 0.0, "count": 0, "health_scores": []})
        for t, amount in tx_amounts:
            category_data[t.category]["amount"] += amount
            category_data[t.category]["count"] += 1
            if t.health_score is not None:
                category_data[t.category]["health_scores"].append(t.health_score)

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
        """Get detailed breakdown for a specific store (split-adjusted).

        For transactions that are part of expense splits, only the user's
        portion is counted. For non-split transactions, the full amount is used.

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

        # Get split-adjusted amounts for all transactions
        tx_amounts = await self.split_calc.get_transaction_user_amounts(user_id, transactions)

        # Calculate totals (split-adjusted)
        total_spend = sum(amount for _, amount in tx_amounts)
        total_items = sum(t.quantity for t in transactions)
        receipt_ids = set(t.receipt_id for t in transactions if t.receipt_id)

        # Calculate average health score for this store
        store_health_scores = [t.health_score for t in transactions if t.health_score is not None]
        store_avg_health = round(sum(store_health_scores) / len(store_health_scores), 2) if store_health_scores else None

        # Calculate average item price (NOT split-adjusted - this is the actual item price)
        total_raw_spend = sum(t.item_price for t in transactions)
        average_item_price = round(total_raw_spend / total_items, 2) if total_items > 0 else None

        # Group by category (split-adjusted)
        category_data = defaultdict(lambda: {"amount": 0.0, "count": 0, "health_scores": []})
        for t, amount in tx_amounts:
            category_data[t.category]["amount"] += amount
            category_data[t.category]["count"] += 1
            if t.health_score is not None:
                category_data[t.category]["health_scores"].append(t.health_score)

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

        # Enrich categories with group info from registry
        registry = get_category_registry()
        from app.services.category_registry import GROUP_COLORS, GROUP_ICONS
        enriched_categories = []
        for cat in categories:
            info = registry.get_info(cat.name)
            group_name = info.group if info else None
            group_color = GROUP_COLORS.get(group_name, "#BDC3C7") if group_name else None
            group_icon = GROUP_ICONS.get(group_name, "square.grid.2x2.fill") if group_name else None
            enriched_categories.append(
                CategorySpending(
                    name=cat.name,
                    spent=cat.spent,
                    percentage=cat.percentage,
                    transaction_count=cat.transaction_count,
                    average_health_score=cat.average_health_score,
                    group=group_name,
                    group_color_hex=group_color,
                    group_icon=group_icon,
                )
            )

        return StoreBreakdown(
            store_name=store_name,
            period=period_str,
            start_date=actual_start,
            end_date=actual_end,
            total_store_spend=round(total_spend, 2),
            store_visits=len(receipt_ids),
            categories=enriched_categories,
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
        Get spending trends over time (split-adjusted).

        For transactions that are part of expense splits, only the user's
        portion is counted. For non-split transactions, the full amount is used.

        Only returns periods that have actual transactions (no empty periods).
        """
        today = date.today()

        # Calculate the earliest date we should look back to
        if period_type == "week":
            earliest_start = today - timedelta(weeks=num_periods)
        elif period_type == "month":
            month = today.month - num_periods
            year = today.year
            while month <= 0:
                month += 12
                year -= 1
            earliest_start = date(year, month, 1)
        else:  # year
            earliest_start = date(today.year - num_periods, 1, 1)

        # Fetch all transactions in the range
        query = select(Transaction).where(
            and_(
                Transaction.user_id == user_id,
                Transaction.date >= earliest_start,
            )
        )
        result = await self.db.execute(query)
        transactions = list(result.scalars().all())

        if not transactions:
            return TrendsResponse(trends=[], period_type=period_type)

        # Get split-adjusted amounts for all transactions
        tx_amounts = await self.split_calc.get_transaction_user_amounts(user_id, transactions)

        # Group transactions by period
        period_data = defaultdict(lambda: {
            "total_spend": 0.0,
            "transaction_count": 0,
            "health_scores": [],
        })

        for t, amount in tx_amounts:
            # Determine period start based on period_type
            if period_type == "week":
                # Get Monday of the week
                days_since_monday = t.date.weekday()
                period_start = t.date - timedelta(days=days_since_monday)
            elif period_type == "month":
                period_start = t.date.replace(day=1)
            else:  # year
                period_start = date(t.date.year, 1, 1)

            pd = period_data[period_start]
            pd["total_spend"] += amount
            pd["transaction_count"] += 1
            if t.health_score is not None:
                pd["health_scores"].append(t.health_score)

        # Build trends list
        trends = []
        for period_start_date, data in period_data.items():
            if data["total_spend"] <= 0:
                continue

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

            avg_health = (
                round(sum(data["health_scores"]) / len(data["health_scores"]), 2)
                if data["health_scores"]
                else None
            )

            trends.append(
                SpendingTrend(
                    period=self._format_period(period_start_date, period_end_date),
                    start_date=period_start_date,
                    end_date=period_end_date,
                    total_spend=round(data["total_spend"], 2),
                    transaction_count=data["transaction_count"],
                    average_health_score=avg_health,
                )
            )

        # Sort by period_start ascending (oldest first for chart display) and limit
        trends.sort(key=lambda x: x.start_date)
        trends = trends[:num_periods]

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
        Get spending trends over time for a specific store (split-adjusted).

        For transactions that are part of expense splits, only the user's
        portion is counted. For non-split transactions, the full amount is used.

        Only returns periods that have actual transactions (no empty periods).
        """
        today = date.today()

        # Calculate the earliest date we should look back to
        if period_type == "week":
            earliest_start = today - timedelta(weeks=num_periods)
        elif period_type == "month":
            month = today.month - num_periods
            year = today.year
            while month <= 0:
                month += 12
                year -= 1
            earliest_start = date(year, month, 1)
        else:  # year
            earliest_start = date(today.year - num_periods, 1, 1)

        # Fetch all transactions in the range for this store
        query = select(Transaction).where(
            and_(
                Transaction.user_id == user_id,
                Transaction.store_name == store_name,
                Transaction.date >= earliest_start,
            )
        )
        result = await self.db.execute(query)
        transactions = list(result.scalars().all())

        if not transactions:
            return TrendsResponse(trends=[], period_type=period_type)

        # Get split-adjusted amounts for all transactions
        tx_amounts = await self.split_calc.get_transaction_user_amounts(user_id, transactions)

        # Group transactions by period
        period_data = defaultdict(lambda: {
            "total_spend": 0.0,
            "transaction_count": 0,
            "health_scores": [],
        })

        for t, amount in tx_amounts:
            # Determine period start based on period_type
            if period_type == "week":
                # Get Monday of the week
                days_since_monday = t.date.weekday()
                period_start = t.date - timedelta(days=days_since_monday)
            elif period_type == "month":
                period_start = t.date.replace(day=1)
            else:  # year
                period_start = date(t.date.year, 1, 1)

            pd = period_data[period_start]
            pd["total_spend"] += amount
            pd["transaction_count"] += 1
            if t.health_score is not None:
                pd["health_scores"].append(t.health_score)

        # Build trends list
        trends = []
        for period_start_date, data in period_data.items():
            if data["total_spend"] <= 0:
                continue

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

            avg_health = (
                round(sum(data["health_scores"]) / len(data["health_scores"]), 2)
                if data["health_scores"]
                else None
            )

            trends.append(
                SpendingTrend(
                    period=self._format_period(period_start_date, period_end_date),
                    start_date=period_start_date,
                    end_date=period_end_date,
                    total_spend=round(data["total_spend"], 2),
                    transaction_count=data["transaction_count"],
                    average_health_score=avg_health,
                )
            )

        # Sort by period_start ascending (oldest first for chart display) and limit
        trends.sort(key=lambda x: x.start_date)
        trends = trends[:num_periods]

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
        Get lightweight metadata for all periods with data (split-adjusted).

        For transactions that are part of expense splits, only the user's
        portion is counted. For non-split transactions, the full amount is used.

        Returns periods sorted by most recent first.
        """
        today = date.today()

        # Calculate the earliest date we should look back to
        if period_type == "week":
            earliest_start = today - timedelta(weeks=num_periods)
        elif period_type == "month":
            # Go back num_periods months
            month = today.month - num_periods
            year = today.year
            while month <= 0:
                month += 12
                year -= 1
            earliest_start = date(year, month, 1)
        else:  # year
            earliest_start = date(today.year - num_periods, 1, 1)

        # Fetch all transactions in the range
        query = select(Transaction).where(
            and_(
                Transaction.user_id == user_id,
                Transaction.date >= earliest_start,
            )
        )
        result = await self.db.execute(query)
        transactions = list(result.scalars().all())

        if not transactions:
            return PeriodsResponse(periods=[], total_periods=0)

        # Get split-adjusted amounts for all transactions
        tx_amounts = await self.split_calc.get_transaction_user_amounts(user_id, transactions)

        # Group transactions by period
        period_data = defaultdict(lambda: {
            "total_spend": 0.0,
            "receipt_ids": set(),
            "store_names": set(),
            "transaction_count": 0,
            "total_items": 0,
            "health_scores": [],
        })

        for t, amount in tx_amounts:
            # Determine period start based on period_type
            if period_type == "week":
                # Get Monday of the week
                days_since_monday = t.date.weekday()
                period_start = t.date - timedelta(days=days_since_monday)
            elif period_type == "month":
                period_start = t.date.replace(day=1)
            else:  # year
                period_start = date(t.date.year, 1, 1)

            pd = period_data[period_start]
            pd["total_spend"] += amount
            if t.receipt_id:
                pd["receipt_ids"].add(t.receipt_id)
            pd["store_names"].add(t.store_name)
            pd["transaction_count"] += 1
            pd["total_items"] += t.quantity
            if t.health_score is not None:
                pd["health_scores"].append(t.health_score)

        # Build period metadata list
        periods = []
        for period_start_date, data in period_data.items():
            if data["total_spend"] <= 0:
                continue

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

            avg_health = (
                round(sum(data["health_scores"]) / len(data["health_scores"]), 2)
                if data["health_scores"]
                else None
            )

            periods.append(
                PeriodMetadata(
                    period=self._format_period(period_start_date, period_end_date),
                    period_start=period_start_date,
                    period_end=period_end_date,
                    total_spend=round(data["total_spend"], 2),
                    receipt_count=len(data["receipt_ids"]),
                    store_count=len(data["store_names"]),
                    transaction_count=data["transaction_count"],
                    total_items=data["total_items"],
                    average_health_score=avg_health,
                )
            )

        # Sort by period_start descending (most recent first) and limit
        periods.sort(key=lambda x: x.period_start, reverse=True)
        periods = periods[:num_periods]

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

        # Get split-adjusted amounts for all transactions
        tx_amounts = await self.split_calc.get_transaction_user_amounts(user_id, transactions)

        # Calculate totals (split-adjusted)
        total_spend = sum(amount for _, amount in tx_amounts)
        total_transactions = len(transactions)
        total_items = sum(t.quantity for t in transactions)
        receipt_ids = set(t.receipt_id for t in transactions if t.receipt_id)
        total_receipts = len(receipt_ids)

        # Calculate averages
        health_scores = [t.health_score for t in transactions if t.health_score is not None]
        avg_health_score = round(sum(health_scores) / len(health_scores), 2) if health_scores else None

        # Calculate raw total (not split-adjusted) for average item price
        total_raw_spend = sum(t.item_price for t in transactions)

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
            average_item_price=round(total_raw_spend / total_items, 2) if total_items > 0 else 0,
            average_health_score=avg_health_score,
            average_receipts_per_period=round(total_receipts / actual_num_periods, 2),
            average_transactions_per_period=round(total_transactions / actual_num_periods, 2),
            average_items_per_receipt=round(total_items / total_receipts, 2) if total_receipts > 0 else 0,
        )

        # Calculate extremes (max/min spending periods) - using split-adjusted amounts
        extremes = self._get_period_extremes_split_adjusted(tx_amounts, period_type)

        # Calculate top categories (split-adjusted)
        top_categories = await self._calculate_top_categories_split_adjusted(
            user_id, tx_amounts, total_spend, top_categories_limit, min_category_percentage
        )

        # Calculate top stores (split-adjusted)
        top_stores = await self._calculate_top_stores_split_adjusted(user_id, tx_amounts, total_spend, top_stores_limit)

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

    def _get_period_extremes_split_adjusted(
        self,
        tx_amounts: List[tuple],
        period_type: str,
    ) -> AggregateExtremes:
        """Calculate extreme values (max/min spend, highest/lowest health) per period using split-adjusted amounts."""
        if not tx_amounts:
            return AggregateExtremes()

        # Group transactions by period
        period_data = defaultdict(lambda: {"total_spend": 0.0, "health_scores": []})

        for t, amount in tx_amounts:
            # Determine period start based on period_type
            if period_type == "week":
                days_since_monday = t.date.weekday()
                period_start = t.date - timedelta(days=days_since_monday)
            elif period_type == "month":
                period_start = t.date.replace(day=1)
            else:  # year
                period_start = date(t.date.year, 1, 1)

            pd = period_data[period_start]
            pd["total_spend"] += amount
            if t.health_score is not None:
                pd["health_scores"].append(t.health_score)

        if not period_data:
            return AggregateExtremes()

        # Calculate extremes
        max_spend_period = None
        min_spend_period = None
        max_health_period = None
        min_health_period = None
        max_spend = float('-inf')
        min_spend = float('inf')
        max_health = float('-inf')
        min_health = float('inf')

        for period_start_date, data in period_data.items():
            if data["total_spend"] > max_spend:
                max_spend = data["total_spend"]
                max_spend_period = period_start_date
            if data["total_spend"] < min_spend:
                min_spend = data["total_spend"]
                min_spend_period = period_start_date

            if data["health_scores"]:
                avg_health = sum(data["health_scores"]) / len(data["health_scores"])
                if avg_health > max_health:
                    max_health = avg_health
                    max_health_period = period_start_date
                if avg_health < min_health:
                    min_health = avg_health
                    min_health_period = period_start_date

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

        if max_spend_period:
            pe = get_period_end(max_spend_period, period_type)
            max_spending_period = PeriodExtreme(
                period=self._format_period(max_spend_period, pe),
                period_start=max_spend_period,
                period_end=pe,
                total_spend=round(max_spend, 2),
            )

        if min_spend_period:
            pe = get_period_end(min_spend_period, period_type)
            min_spending_period = PeriodExtreme(
                period=self._format_period(min_spend_period, pe),
                period_start=min_spend_period,
                period_end=pe,
                total_spend=round(min_spend, 2),
            )

        if max_health_period:
            pe = get_period_end(max_health_period, period_type)
            highest_health_period = HealthScoreExtreme(
                period=self._format_period(max_health_period, pe),
                period_start=max_health_period,
                period_end=pe,
                average_health_score=round(max_health, 2),
            )

        if min_health_period:
            pe = get_period_end(min_health_period, period_type)
            lowest_health_period = HealthScoreExtreme(
                period=self._format_period(min_health_period, pe),
                period_start=min_health_period,
                period_end=pe,
                average_health_score=round(min_health, 2),
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
            category_data[t.category]["amount"] += t.item_price
            category_data[t.category]["count"] += 1
            if t.health_score is not None:
                category_data[t.category]["health_scores"].append(t.health_score)

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

    async def _calculate_top_categories_split_adjusted(
        self,
        user_id: str,
        tx_amounts: List[tuple],
        total_spend: float,
        limit: int,
        min_percentage: float,
    ) -> list[CategorySpending]:
        """Calculate top categories from transactions with split-adjusted amounts."""
        category_data = defaultdict(lambda: {"amount": 0.0, "count": 0, "health_scores": []})

        for t, amount in tx_amounts:
            category_data[t.category]["amount"] += amount
            category_data[t.category]["count"] += 1
            if t.health_score is not None:
                category_data[t.category]["health_scores"].append(t.health_score)

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

    async def _calculate_top_stores_split_adjusted(
        self,
        user_id: str,
        tx_amounts: List[tuple],
        total_spend: float,
        limit: int,
    ) -> list[StoreSpending]:
        """Calculate top stores from transactions with split-adjusted amounts."""
        store_data = defaultdict(lambda: {"amount": 0.0, "receipt_ids": set(), "health_scores": []})

        for t, amount in tx_amounts:
            store_data[t.store_name]["amount"] += amount
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
        top_categories_limit: int = 5,
    ) -> AllTimeResponse:
        """
        Get all-time statistics for a user (split-adjusted).

        For transactions that are part of expense splits, only the user's
        portion is counted. For non-split transactions, the full amount is used.

        Returns aggregate stats across all user transactions, including:
        - Total receipts, items, spend, transactions
        - Average item price and health score
        - Top stores by visits and spend
        - Top categories by spend
        - First and last receipt dates
        """

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
                top_categories=[],
                first_receipt_date=None,
                last_receipt_date=None,
            )

        # Get split-adjusted amounts for all transactions
        tx_amounts = await self.split_calc.get_transaction_user_amounts(user_id, transactions)

        # Calculate totals (split-adjusted)
        total_spend = sum(amount for _, amount in tx_amounts)
        total_transactions = len(transactions)
        total_items = sum(t.quantity for t in transactions)
        receipt_ids = set(t.receipt_id for t in transactions if t.receipt_id)
        total_receipts = len(receipt_ids)

        # Calculate averages
        # Note: average_item_price uses raw prices (NOT split-adjusted) - it's the actual item cost
        total_raw_spend = sum(t.item_price for t in transactions)
        average_item_price = round(total_raw_spend / total_items, 2) if total_items > 0 else None
        health_scores = [t.health_score for t in transactions if t.health_score is not None]
        average_health_score = round(sum(health_scores) / len(health_scores), 2) if health_scores else None

        # Calculate first and last receipt dates
        dates = [t.date for t in transactions]
        first_receipt_date = min(dates)
        last_receipt_date = max(dates)

        # Calculate top stores by visits (visits not affected by splits)
        store_visits = defaultdict(set)
        store_spend = defaultdict(float)
        for t, amount in tx_amounts:
            if t.receipt_id:
                store_visits[t.store_name].add(t.receipt_id)
            store_spend[t.store_name] += amount

        # Top by visits
        stores_by_visits = [
            {"store_name": name, "visit_count": len(rids)}
            for name, rids in store_visits.items()
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

        # Top by spend (split-adjusted)
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

        # Calculate top categories (split-adjusted)
        category_data = defaultdict(lambda: {"amount": 0.0, "count": 0, "health_scores": []})
        for t, amount in tx_amounts:
            category_data[t.category]["amount"] += amount
            category_data[t.category]["count"] += 1
            if t.health_score is not None:
                category_data[t.category]["health_scores"].append(t.health_score)

        categories_list = []
        for category_name, data in category_data.items():
            percentage = (data["amount"] / total_spend * 100) if total_spend > 0 else 0
            avg_health = (
                round(sum(data["health_scores"]) / len(data["health_scores"]), 2)
                if data["health_scores"]
                else None
            )
            categories_list.append({
                "name": category_name,
                "total_spent": round(data["amount"], 2),
                "percentage": round(percentage, 1),
                "transaction_count": data["count"],
                "average_health_score": avg_health,
            })

        categories_list.sort(key=lambda x: x["total_spent"], reverse=True)
        top_categories = [
            TopCategory(
                name=c["name"],
                total_spent=c["total_spent"],
                percentage=c["percentage"],
                transaction_count=c["transaction_count"],
                average_health_score=c["average_health_score"],
                rank=i + 1,
            )
            for i, c in enumerate(categories_list[:top_categories_limit])
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
            top_categories=top_categories,
            first_receipt_date=first_receipt_date,
            last_receipt_date=last_receipt_date,
        )

    async def get_year_summary(
        self,
        user_id: str,
        year: int,
        include_monthly_breakdown: bool = True,
        top_categories_limit: int = 5,
    ) -> YearSummaryResponse:
        """
        Get aggregated analytics data for a specific year.

        Args:
            user_id: The user's ID
            year: The year to fetch data for (e.g., 2025)
            include_monthly_breakdown: Whether to include per-month spending breakdown
            top_categories_limit: Number of top categories to return

        Returns:
            YearSummaryResponse with total spending, store breakdowns, and optional monthly breakdown
        """

        # Define year boundaries
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)

        # Get all transactions for the year
        query = select(Transaction).where(
            and_(
                Transaction.user_id == user_id,
                Transaction.date >= start_date,
                Transaction.date <= end_date,
            )
        )
        result = await self.db.execute(query)
        transactions = list(result.scalars().all())

        # Return empty response if no transactions
        if not transactions:
            return YearSummaryResponse(
                year=year,
                start_date=start_date,
                end_date=end_date,
                total_spend=0,
                transaction_count=0,
                receipt_count=0,
                total_items=0,
                average_health_score=None,
                stores=[],
                monthly_breakdown=[] if include_monthly_breakdown else None,
                top_categories=[],
            )

        # Get split-adjusted amounts for all transactions
        tx_amounts = await self.split_calc.get_transaction_user_amounts(user_id, transactions)

        # Calculate totals (split-adjusted)
        total_spend = sum(amount for _, amount in tx_amounts)
        transaction_count = len(transactions)
        total_items = sum(t.quantity for t in transactions)
        receipt_ids = set(t.receipt_id for t in transactions if t.receipt_id)
        receipt_count = len(receipt_ids)

        # Calculate average health score
        health_scores = [t.health_score for t in transactions if t.health_score is not None]
        average_health_score = round(sum(health_scores) / len(health_scores), 2) if health_scores else None

        # Aggregate store data (split-adjusted)
        store_data = defaultdict(lambda: {"amount": 0.0, "receipt_ids": set(), "health_scores": []})
        for t, amount in tx_amounts:
            store_data[t.store_name]["amount"] += amount
            if t.receipt_id:
                store_data[t.store_name]["receipt_ids"].add(t.receipt_id)
            if t.health_score is not None:
                store_data[t.store_name]["health_scores"].append(t.health_score)

        # Build store list sorted by amount_spent descending
        stores = []
        for store_name, data in store_data.items():
            percentage = (data["amount"] / total_spend * 100) if total_spend > 0 else 0
            store_avg_health = (
                round(sum(data["health_scores"]) / len(data["health_scores"]), 2)
                if data["health_scores"]
                else None
            )
            stores.append(
                YearStoreSpending(
                    store_name=store_name,
                    amount_spent=round(data["amount"], 2),
                    store_visits=len(data["receipt_ids"]),
                    percentage=round(percentage, 1),
                    average_health_score=store_avg_health,
                )
            )
        stores.sort(key=lambda x: x.amount_spent, reverse=True)

        # Calculate monthly breakdown if requested (split-adjusted)
        monthly_breakdown = None
        if include_monthly_breakdown:
            month_data = defaultdict(lambda: {"amount": 0.0, "receipt_ids": set(), "health_scores": []})
            for t, amount in tx_amounts:
                month_num = t.date.month
                month_data[month_num]["amount"] += amount
                if t.receipt_id:
                    month_data[month_num]["receipt_ids"].add(t.receipt_id)
                if t.health_score is not None:
                    month_data[month_num]["health_scores"].append(t.health_score)

            # Build monthly breakdown list, only including months with data
            month_names = [
                "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"
            ]
            monthly_breakdown = []
            for month_num in sorted(month_data.keys()):
                data = month_data[month_num]
                month_avg_health = (
                    round(sum(data["health_scores"]) / len(data["health_scores"]), 2)
                    if data["health_scores"]
                    else None
                )
                monthly_breakdown.append(
                    YearMonthlyBreakdown(
                        month=month_names[month_num - 1],
                        month_number=month_num,
                        total_spend=round(data["amount"], 2),
                        receipt_count=len(data["receipt_ids"]),
                        average_health_score=month_avg_health,
                    )
                )

        # Calculate top categories (split-adjusted)
        category_data = defaultdict(lambda: {"amount": 0.0, "count": 0, "health_scores": []})
        for t, amount in tx_amounts:
            category_data[t.category]["amount"] += amount
            category_data[t.category]["count"] += 1
            if t.health_score is not None:
                category_data[t.category]["health_scores"].append(t.health_score)

        categories = []
        for category_name, data in category_data.items():
            percentage = (data["amount"] / total_spend * 100) if total_spend > 0 else 0
            cat_avg_health = (
                round(sum(data["health_scores"]) / len(data["health_scores"]), 2)
                if data["health_scores"]
                else None
            )
            categories.append(
                YearCategorySpending(
                    name=category_name,
                    spent=round(data["amount"], 2),
                    percentage=round(percentage, 1),
                    transaction_count=data["count"],
                    average_health_score=cat_avg_health,
                )
            )

        # Sort by spent descending and limit
        categories.sort(key=lambda x: x.spent, reverse=True)
        top_categories = categories[:top_categories_limit]

        return YearSummaryResponse(
            year=year,
            start_date=start_date,
            end_date=end_date,
            total_spend=round(total_spend, 2),
            transaction_count=transaction_count,
            receipt_count=receipt_count,
            total_items=total_items,
            average_health_score=average_health_score,
            stores=stores,
            monthly_breakdown=monthly_breakdown,
            top_categories=top_categories,
        )

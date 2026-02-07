"""Budget insights service - deterministic, rule-based insights without AI."""

import calendar
import statistics
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.models.budget import Budget
from app.models.budget_history import BudgetHistory
from app.schemas.budget_insights import (
    BelgianBenchmarkComparison,
    BelgianBenchmarksResponse,
    OverBudgetFlag,
    OverBudgetFlagsResponse,
    QuickWin,
    QuickWinsResponse,
    VolatilityAlert,
    VolatilityAlertsResponse,
    RichProgressResponse,
    HealthScoreBreakdown,
    BudgetInsightsResponse,
)
from app.services.split_aware_calculation import SplitAwareCalculation


class BudgetInsightsService:
    """Service for calculating budget insights without AI.

    All calculations are deterministic and formula-based.
    """

    # Belgian household averages (source: Belgian Household Budget Survey)
    # Percentages of total grocery/household spending
    BELGIAN_AVERAGES = {
        "Groceries": 25.0,
        "Fresh Produce": 8.0,
        "Meat & Fish": 12.0,
        "Dairy": 8.0,
        "Bakery": 5.0,
        "Beverages": 10.0,
        "Alcohol": 5.0,
        "Snacks & Treats": 6.0,
        "Snacks & Sweets": 6.0,
        "Household": 10.0,
        "Personal Care": 6.0,
        "Frozen": 3.0,
        "Pantry": 2.0,
    }

    # Categories considered discretionary (good targets for quick wins)
    DISCRETIONARY_CATEGORIES = {
        "Alcohol",
        "Snacks & Treats",
        "Snacks & Sweets",
        "Beverages",
        "Frozen",
    }

    def __init__(self, db: AsyncSession):
        self.db = db
        self.split_calc = SplitAwareCalculation(db)

    async def _get_monthly_spend_by_category(
        self, user_id: str, months: int = 3
    ) -> dict[str, list[float]]:
        """Get monthly spending per category for the last N complete months.

        Returns dict mapping category -> list of monthly spend values.
        """
        today = date.today()
        end_date = today.replace(day=1)  # First of current month (exclusive)

        year = end_date.year
        month = end_date.month - months
        while month <= 0:
            month += 12
            year -= 1
        start_date = date(year, month, 1)

        # Get all transactions
        result = await self.db.execute(
            select(Transaction).where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= start_date,
                    Transaction.date < end_date,
                )
            )
        )
        transactions = list(result.scalars().all())

        if not transactions:
            return {}

        # Get split-adjusted amounts
        tx_amounts = await self.split_calc.get_transaction_user_amounts(
            user_id, transactions
        )

        # Group by month and category
        monthly_category_spend: dict[str, dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )

        for tx, amount in tx_amounts:
            month_key = f"{tx.date.year}-{tx.date.month:02d}"
            monthly_category_spend[month_key][tx.category] += amount

        # Convert to category -> list of monthly values
        all_categories = set()
        for month_data in monthly_category_spend.values():
            all_categories.update(month_data.keys())

        result_dict: dict[str, list[float]] = {}
        for category in all_categories:
            monthly_values = []
            for month_key in sorted(monthly_category_spend.keys()):
                monthly_values.append(monthly_category_spend[month_key].get(category, 0))
            result_dict[category] = monthly_values

        return result_dict

    async def _get_budget_history_allocations(
        self, user_id: str, months: int = 3
    ) -> dict[str, list[tuple[float, float]]]:
        """Get historical budget allocations and actual spend per category.

        Returns dict mapping category -> list of (allocated, spent) tuples.
        """
        today = date.today()

        # Get budget history for last N months
        month_keys = []
        for i in range(1, months + 1):
            year = today.year
            month = today.month - i
            while month <= 0:
                month += 12
                year -= 1
            month_keys.append(f"{year}-{month:02d}")

        result = await self.db.execute(
            select(BudgetHistory).where(
                and_(
                    BudgetHistory.user_id == user_id,
                    BudgetHistory.month.in_(month_keys),
                    BudgetHistory.was_deleted == False,
                )
            )
        )
        history_entries = list(result.scalars().all())

        if not history_entries:
            return {}

        # Get monthly spending
        monthly_spend = await self._get_monthly_spend_by_category(user_id, months)

        # Match allocations to spending
        category_history: dict[str, list[tuple[float, float]]] = defaultdict(list)

        for entry in history_entries:
            if not entry.category_allocations:
                continue

            # Get spending for this month
            month_idx = month_keys.index(entry.month) if entry.month in month_keys else -1
            if month_idx < 0:
                continue

            for alloc in entry.category_allocations:
                category = alloc.get("category", "")
                allocated = alloc.get("amount", 0)
                spent = (
                    monthly_spend.get(category, [0] * months)[month_idx]
                    if category in monthly_spend
                    else 0
                )
                category_history[category].append((allocated, spent))

        return category_history

    async def get_belgian_benchmarks(
        self, user_id: str
    ) -> BelgianBenchmarksResponse:
        """Compare user spending to Belgian household averages."""
        monthly_spend = await self._get_monthly_spend_by_category(user_id, months=3)

        if not monthly_spend:
            return BelgianBenchmarksResponse(
                comparisons=[],
                user_total_analyzed=0,
            )

        # Calculate user's average monthly spend per category
        category_averages: dict[str, float] = {}
        for category, monthly_values in monthly_spend.items():
            if monthly_values:
                category_averages[category] = sum(monthly_values) / len(monthly_values)

        total_user_spend = sum(category_averages.values())

        if total_user_spend == 0:
            return BelgianBenchmarksResponse(
                comparisons=[],
                user_total_analyzed=0,
            )

        # Calculate percentages and compare
        comparisons = []
        for category, avg_spend in sorted(
            category_averages.items(), key=lambda x: x[1], reverse=True
        ):
            user_pct = (avg_spend / total_user_spend) * 100
            belgian_pct = self.BELGIAN_AVERAGES.get(category, 5.0)  # Default 5%
            diff_pct = user_pct - belgian_pct

            # Generate comparison text
            if abs(diff_pct) < 2:
                comparison_text = f"Your {category} spending is typical for Belgian households"
            elif diff_pct > 0:
                comparison_text = f"You spend {abs(diff_pct):.0f}% more on {category} than typical Belgian households"
            else:
                comparison_text = f"You spend {abs(diff_pct):.0f}% less on {category} than typical Belgian households"

            comparisons.append(
                BelgianBenchmarkComparison(
                    category=category,
                    user_percentage=round(user_pct, 1),
                    belgian_average_percentage=belgian_pct,
                    difference_percentage=round(diff_pct, 1),
                    comparison_text=comparison_text,
                )
            )

        return BelgianBenchmarksResponse(
            comparisons=comparisons,
            user_total_analyzed=round(total_user_spend * 3, 2),  # 3 months
        )

    async def get_over_budget_flags(
        self, user_id: str, months: int = 3
    ) -> OverBudgetFlagsResponse:
        """Identify categories consistently over budget."""
        category_history = await self._get_budget_history_allocations(user_id, months)

        if not category_history:
            return OverBudgetFlagsResponse(flags=[], months_analyzed=0)

        flags = []
        for category, history in category_history.items():
            if not history:
                continue

            # Count months over budget
            over_months = 0
            total_overage_pct = 0
            total_overage_amount = 0

            for allocated, spent in history:
                if allocated > 0 and spent > allocated:
                    over_months += 1
                    overage = spent - allocated
                    total_overage_pct += (overage / allocated) * 100
                    total_overage_amount += overage

            months_analyzed = len(history)

            # Flag if over 2+ months
            if over_months >= 2:
                avg_overage_pct = total_overage_pct / over_months if over_months > 0 else 0
                avg_overage_amt = total_overage_amount / over_months if over_months > 0 else 0

                severity = "critical" if over_months >= months_analyzed else "warning"

                flags.append(
                    OverBudgetFlag(
                        category=category,
                        months_over=over_months,
                        months_analyzed=months_analyzed,
                        average_overage_percentage=round(avg_overage_pct, 1),
                        average_overage_amount=round(avg_overage_amt, 2),
                        severity=severity,
                    )
                )

        # Sort by severity then overage
        flags.sort(
            key=lambda x: (x.severity == "critical", x.average_overage_amount),
            reverse=True,
        )

        return OverBudgetFlagsResponse(
            flags=flags,
            months_analyzed=months,
        )

    async def get_quick_wins(self, user_id: str) -> QuickWinsResponse:
        """Calculate potential savings from cutting discretionary categories."""
        monthly_spend = await self._get_monthly_spend_by_category(user_id, months=3)

        if not monthly_spend:
            return QuickWinsResponse(
                quick_wins=[],
                total_potential_monthly_savings=0,
                total_potential_yearly_savings=0,
            )

        quick_wins = []
        total_monthly = 0
        total_yearly = 0

        for category, monthly_values in monthly_spend.items():
            if not monthly_values:
                continue

            avg_monthly = sum(monthly_values) / len(monthly_values)

            # Only suggest cuts for discretionary categories or high-spend categories
            is_discretionary = category in self.DISCRETIONARY_CATEGORIES
            is_high_spend = avg_monthly > 50  # More than €50/month

            if is_discretionary or is_high_spend:
                cut_pct = 10 if is_discretionary else 15
                monthly_savings = avg_monthly * (cut_pct / 100)
                yearly_savings = monthly_savings * 12

                if monthly_savings >= 5:  # Only show if savings are meaningful
                    message = f"Save €{monthly_savings:.0f}/month on {category} = €{yearly_savings:.0f}/year"

                    quick_wins.append(
                        QuickWin(
                            category=category,
                            current_monthly_spend=round(avg_monthly, 2),
                            suggested_cut_percentage=cut_pct,
                            monthly_savings=round(monthly_savings, 2),
                            yearly_savings=round(yearly_savings, 2),
                            message=message,
                        )
                    )

                    total_monthly += monthly_savings
                    total_yearly += yearly_savings

        # Sort by yearly savings
        quick_wins.sort(key=lambda x: x.yearly_savings, reverse=True)

        return QuickWinsResponse(
            quick_wins=quick_wins[:5],  # Top 5 opportunities
            total_potential_monthly_savings=round(total_monthly, 2),
            total_potential_yearly_savings=round(total_yearly, 2),
        )

    async def get_volatility_alerts(
        self, user_id: str, months: int = 3
    ) -> VolatilityAlertsResponse:
        """Identify categories with high month-to-month variance."""
        monthly_spend = await self._get_monthly_spend_by_category(user_id, months)

        if not monthly_spend:
            return VolatilityAlertsResponse(alerts=[], months_analyzed=0)

        alerts = []
        for category, monthly_values in monthly_spend.items():
            # Need at least 2 months for variance calculation
            if len(monthly_values) < 2:
                continue

            # Filter out zero months for more accurate stats
            non_zero_values = [v for v in monthly_values if v > 0]
            if len(non_zero_values) < 2:
                continue

            avg = statistics.mean(non_zero_values)
            if avg < 10:  # Ignore very small categories
                continue

            stddev = statistics.stdev(non_zero_values)
            cv = (stddev / avg) * 100  # Coefficient of variation

            # Determine volatility level
            if cv >= 60:
                volatility_level = "very_high"
            elif cv >= 40:
                volatility_level = "high"
            elif cv >= 25:
                volatility_level = "moderate"
            else:
                continue  # Not volatile enough to alert

            min_spend = min(non_zero_values)
            max_spend = max(non_zero_values)

            # Generate recommendation
            buffer = round(stddev, 0)
            recommendation = f"Budget €{buffer:.0f} buffer for unpredictable {category} spending"

            alerts.append(
                VolatilityAlert(
                    category=category,
                    average_monthly_spend=round(avg, 2),
                    standard_deviation=round(stddev, 2),
                    coefficient_of_variation=round(cv, 1),
                    min_month_spend=round(min_spend, 2),
                    max_month_spend=round(max_spend, 2),
                    volatility_level=volatility_level,
                    recommendation=recommendation,
                )
            )

        # Sort by CV descending
        alerts.sort(key=lambda x: x.coefficient_of_variation, reverse=True)

        return VolatilityAlertsResponse(
            alerts=alerts,
            months_analyzed=months,
        )

    async def get_rich_progress(
        self, user_id: str, budget: Budget
    ) -> RichProgressResponse:
        """Calculate rich progress metrics including health score."""
        today = date.today()
        first_of_month = today.replace(day=1)

        # Get current month spending
        result = await self.db.execute(
            select(Transaction).where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= first_of_month,
                    Transaction.date <= today,
                )
            )
        )
        transactions = list(result.scalars().all())

        current_spend = 0.0
        if transactions:
            current_spend = await self.split_calc.calculate_split_adjusted_spend(
                user_id, transactions
            )

        # Calculate days
        days_elapsed = today.day
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        days_remaining = days_in_month - days_elapsed

        # Calculate daily budget remaining
        remaining_budget = max(0, budget.monthly_amount - current_spend)
        daily_remaining = remaining_budget / days_remaining if days_remaining > 0 else 0

        # Calculate projection
        if days_elapsed > 0:
            daily_rate = current_spend / days_elapsed
            projected = daily_rate * days_in_month
        else:
            projected = 0

        # Determine projected status
        buffer = budget.monthly_amount * 0.05  # 5% buffer for "on track"
        projected_diff = budget.monthly_amount - projected

        if projected <= budget.monthly_amount - buffer:
            projected_status = "under_budget"
        elif projected <= budget.monthly_amount + buffer:
            projected_status = "on_track"
        else:
            projected_status = "over_budget"

        # Calculate health score
        health_breakdown = await self._calculate_health_score(
            user_id, budget, current_spend, days_elapsed, days_in_month
        )

        total_score = (
            health_breakdown.pace_score
            + health_breakdown.category_balance_score
            + health_breakdown.consistency_score
        )
        total_score = min(100, max(0, total_score))

        # Health label
        if total_score >= 80:
            health_label = "Excellent"
        elif total_score >= 60:
            health_label = "Good"
        elif total_score >= 40:
            health_label = "Fair"
        else:
            health_label = "Needs Attention"

        return RichProgressResponse(
            daily_budget_remaining=round(daily_remaining, 2),
            days_remaining=days_remaining,
            projected_end_of_month=round(projected, 2),
            projected_status=projected_status,
            projected_difference=round(projected_diff, 2),
            health_score=total_score,
            health_score_breakdown=health_breakdown,
            health_score_label=health_label,
        )

    async def _calculate_health_score(
        self,
        user_id: str,
        budget: Budget,
        current_spend: float,
        days_elapsed: int,
        days_in_month: int,
    ) -> HealthScoreBreakdown:
        """Calculate formula-based health score breakdown."""
        # Pace score (0-40 points)
        # Perfect pace = 40, deduct for being over pace
        expected_spend = (days_elapsed / days_in_month) * budget.monthly_amount
        if expected_spend > 0:
            pace_ratio = current_spend / expected_spend
            if pace_ratio <= 1.0:
                pace_score = 40  # At or under pace = full points
            else:
                # Deduct proportionally for being over pace
                over_pct = (pace_ratio - 1) * 100
                pace_score = max(0, 40 - int(over_pct * 0.8))
        else:
            pace_score = 40  # First day of month

        # Category balance score (0-30 points)
        # Deduct 6 points per over-budget category
        over_budget_count = 0
        if budget.category_allocations:
            # Get current month category spending
            today = date.today()
            first_of_month = today.replace(day=1)
            result = await self.db.execute(
                select(Transaction).where(
                    and_(
                        Transaction.user_id == user_id,
                        Transaction.date >= first_of_month,
                        Transaction.date <= today,
                    )
                )
            )
            transactions = list(result.scalars().all())

            if transactions:
                category_spend = (
                    await self.split_calc.calculate_split_adjusted_spend_by_category(
                        user_id, transactions
                    )
                )

                for alloc in budget.category_allocations:
                    category = alloc.get("category", "")
                    allocated = alloc.get("amount", 0)
                    spent = category_spend.get(category, 0)
                    if spent > allocated:
                        over_budget_count += 1

        category_score = max(0, 30 - (over_budget_count * 6))

        # Consistency score (0-30 points)
        # Based on volatility - fewer high-variance categories = higher score
        volatility_response = await self.get_volatility_alerts(user_id, months=3)
        high_volatility_count = sum(
            1
            for alert in volatility_response.alerts
            if alert.volatility_level in ("high", "very_high")
        )
        consistency_score = max(0, 30 - (high_volatility_count * 5))

        return HealthScoreBreakdown(
            pace_score=pace_score,
            category_balance_score=category_score,
            consistency_score=consistency_score,
        )

    async def get_all_insights(
        self,
        user_id: str,
        budget: Optional[Budget] = None,
        include_benchmarks: bool = True,
        include_flags: bool = True,
        include_quick_wins: bool = True,
        include_volatility: bool = True,
        include_progress: bool = True,
    ) -> BudgetInsightsResponse:
        """Get all budget insights in a single response."""
        today = date.today()

        belgian_benchmarks = None
        over_budget_flags = None
        quick_wins = None
        volatility_alerts = None
        rich_progress = None

        if include_benchmarks:
            belgian_benchmarks = await self.get_belgian_benchmarks(user_id)

        if include_flags:
            over_budget_flags = await self.get_over_budget_flags(user_id)

        if include_quick_wins:
            quick_wins = await self.get_quick_wins(user_id)

        if include_volatility:
            volatility_alerts = await self.get_volatility_alerts(user_id)

        if include_progress and budget:
            rich_progress = await self.get_rich_progress(user_id, budget)

        return BudgetInsightsResponse(
            belgian_benchmarks=belgian_benchmarks,
            over_budget_flags=over_budget_flags,
            quick_wins=quick_wins,
            volatility_alerts=volatility_alerts,
            rich_progress=rich_progress,
            generated_at=datetime.utcnow(),
            data_freshness=f"Based on spending through {today.strftime('%b %d, %Y')}",
        )

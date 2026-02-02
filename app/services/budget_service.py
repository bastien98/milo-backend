import calendar
from datetime import date
from typing import List, Optional
from collections import defaultdict

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.models.budget import Budget
from app.schemas.budget import (
    BudgetResponse,
    BudgetProgressResponse,
    CategoryProgress,
    BudgetSuggestionResponse,
    CategoryBreakdown,
    SavingsOption,
    CategoryAllocation,
)


def category_name_to_id(category_name: str) -> str:
    """Convert category display name to ID format."""
    return category_name.upper().replace(" ", "_").replace("&", "").replace("(", "").replace(")", "").replace("/", "_").replace("-", "_")


class BudgetService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_current_month_spend(self, user_id: str) -> float:
        """Get total spending for the current month."""
        today = date.today()
        first_day = today.replace(day=1)

        result = await self.db.execute(
            select(func.coalesce(func.sum(Transaction.item_price), 0)).where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= first_day,
                    Transaction.date <= today,
                )
            )
        )
        return float(result.scalar() or 0)

    async def get_current_month_spend_by_category(
        self, user_id: str
    ) -> dict[str, float]:
        """Get spending by category for the current month."""
        today = date.today()
        first_day = today.replace(day=1)

        result = await self.db.execute(
            select(
                Transaction.category,
                func.coalesce(func.sum(Transaction.item_price), 0).label("spent"),
            )
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= first_day,
                    Transaction.date <= today,
                )
            )
            .group_by(Transaction.category)
        )

        # Convert enum values to their display names
        return {row.category.value: float(row.spent) for row in result.all()}

    async def get_historical_category_percentages(
        self, user_id: str, months: int = 3
    ) -> dict[str, float]:
        """Get historical spending percentages by category.

        Returns a dict mapping category display names to their percentage of total spend.
        """
        today = date.today()

        # Calculate date range for last N complete months
        end_date = today.replace(day=1)  # First day of current month (exclusive)

        year = end_date.year
        month = end_date.month - months
        while month <= 0:
            month += 12
            year -= 1
        start_date = date(year, month, 1)

        # Get total spend in the period
        total_result = await self.db.execute(
            select(func.coalesce(func.sum(Transaction.item_price), 0)).where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= start_date,
                    Transaction.date < end_date,
                )
            )
        )
        total_spend = float(total_result.scalar() or 0)

        if total_spend == 0:
            return {}

        # Get spend by category
        category_result = await self.db.execute(
            select(
                Transaction.category,
                func.sum(Transaction.item_price).label("spent"),
            )
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= start_date,
                    Transaction.date < end_date,
                )
            )
            .group_by(Transaction.category)
        )

        return {
            row.category.value: float(row.spent) / total_spend
            for row in category_result.all()
        }

    async def get_budget_progress(
        self, user_id: str, budget: Budget
    ) -> BudgetProgressResponse:
        """Calculate budget progress with spending data for the current month.

        For each category with spending this month:
        - If category_allocations exist, use the allocated budget_amount
        - If no category_allocations, auto-distribute monthly budget proportionally
          based on historical spending patterns
        """
        today = date.today()

        # Get current month spend (total and by category)
        current_spend = await self.get_current_month_spend(user_id)
        spend_by_category = await self.get_current_month_spend_by_category(user_id)

        # Calculate days elapsed and days in month
        days_elapsed = today.day
        days_in_month = calendar.monthrange(today.year, today.month)[1]

        # Calculate category progress
        category_progress: List[CategoryProgress] = []

        if budget.category_allocations:
            # Use explicit category allocations
            # Build a lookup for allocated categories
            allocations_by_category = {
                alloc.get("category", ""): alloc
                for alloc in budget.category_allocations
            }

            # Include all categories with spending this month
            all_categories = set(spend_by_category.keys()) | set(allocations_by_category.keys())

            for category_name in all_categories:
                category_spend = spend_by_category.get(category_name, 0)
                allocation = allocations_by_category.get(category_name)

                if allocation:
                    # Use explicit allocation
                    limit_amount = allocation.get("amount", 0)
                    is_locked = allocation.get("is_locked", False)
                else:
                    # Category has spending but no allocation - set limit_amount to 0
                    limit_amount = 0
                    is_locked = False

                # Calculate over budget status
                is_over_budget = category_spend > limit_amount
                over_budget_amount = round(category_spend - limit_amount, 2) if is_over_budget else None

                # Get category_id from display name
                category_id = category_name_to_id(category_name)

                category_progress.append(
                    CategoryProgress(
                        category_id=category_id,
                        name=category_name,
                        limit_amount=limit_amount,
                        spent_amount=category_spend,
                        is_over_budget=is_over_budget,
                        over_budget_amount=over_budget_amount,
                        is_locked=is_locked,
                    )
                )
        else:
            # No explicit allocations - auto-distribute based on historical patterns
            historical_percentages = await self.get_historical_category_percentages(user_id)

            for category_name, category_spend in spend_by_category.items():
                # Calculate budget amount based on historical percentage
                historical_pct = historical_percentages.get(category_name, 0)

                if historical_pct > 0:
                    limit_amount = budget.monthly_amount * historical_pct
                else:
                    # No historical data for this category - allocate proportionally
                    # based on current month's spending pattern
                    if current_spend > 0:
                        limit_amount = (category_spend / current_spend) * budget.monthly_amount
                    else:
                        limit_amount = 0

                limit_amount = round(limit_amount, 2)

                # Calculate over budget status
                is_over_budget = category_spend > limit_amount
                over_budget_amount = round(category_spend - limit_amount, 2) if is_over_budget else None

                # Get category_id from display name
                category_id = category_name_to_id(category_name)

                category_progress.append(
                    CategoryProgress(
                        category_id=category_id,
                        name=category_name,
                        limit_amount=limit_amount,
                        spent_amount=category_spend,
                        is_over_budget=is_over_budget,
                        over_budget_amount=over_budget_amount,
                        is_locked=False,  # Auto-distributed allocations are never locked
                    )
                )

        # Sort by spent_amount descending for better UX
        category_progress.sort(key=lambda x: x.spent_amount, reverse=True)

        # Convert budget to response format
        budget_response = BudgetResponse(
            id=budget.id,
            user_id=budget.user_id,
            monthly_amount=budget.monthly_amount,
            category_allocations=[
                CategoryAllocation(**alloc)
                for alloc in (budget.category_allocations or [])
            ]
            if budget.category_allocations
            else None,
            notifications_enabled=budget.notifications_enabled,
            alert_thresholds=budget.alert_thresholds,
            is_smart_budget=budget.is_smart_budget,
            created_at=budget.created_at,
            updated_at=budget.updated_at,
        )

        return BudgetProgressResponse(
            budget=budget_response,
            current_spend=current_spend,
            days_elapsed=days_elapsed,
            days_in_month=days_in_month,
            category_progress=category_progress,
        )

    async def get_budget_suggestion(
        self, user_id: str, months: int = 3
    ) -> Optional[BudgetSuggestionResponse]:
        """Generate a smart budget suggestion based on historical spending."""
        today = date.today()

        # Calculate the date range for the last N complete months
        # We want complete months only, so exclude the current month
        end_date = today.replace(day=1)  # First day of current month (exclusive)

        # Go back N months from the start of current month
        year = end_date.year
        month = end_date.month - months
        while month <= 0:
            month += 12
            year -= 1
        start_date = date(year, month, 1)

        # Get monthly totals for the period
        monthly_totals_query = await self.db.execute(
            select(
                func.date_trunc("month", Transaction.date).label("month"),
                func.sum(Transaction.item_price).label("monthly_spend"),
            )
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= start_date,
                    Transaction.date < end_date,
                )
            )
            .group_by(func.date_trunc("month", Transaction.date))
        )
        monthly_totals = monthly_totals_query.all()

        if not monthly_totals:
            return None

        # Calculate average monthly spend
        total_spend = sum(row.monthly_spend for row in monthly_totals)
        num_months = len(monthly_totals)
        average_monthly_spend = total_spend / num_months

        # Get category breakdown
        category_totals_query = await self.db.execute(
            select(
                Transaction.category,
                func.sum(Transaction.item_price).label("total_spent"),
            )
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= start_date,
                    Transaction.date < end_date,
                )
            )
            .group_by(Transaction.category)
        )
        category_totals = category_totals_query.all()

        # Calculate category breakdown
        category_breakdown: List[CategoryBreakdown] = []
        for row in category_totals:
            category_name = row.category.value  # Get display name from enum
            average_spend = float(row.total_spent) / num_months
            percentage = (average_spend / average_monthly_spend * 100) if average_monthly_spend > 0 else 0

            category_breakdown.append(
                CategoryBreakdown(
                    category=category_name,
                    average_spend=round(average_spend, 2),
                    suggested_budget=round(average_spend, 2),
                    percentage=round(percentage, 1),
                )
            )

        # Sort by average spend descending
        category_breakdown.sort(key=lambda x: x.average_spend, reverse=True)

        # Round suggested amount to nearest €5
        suggested_amount = round(average_monthly_spend / 5) * 5

        # Generate savings options
        savings_options = [
            SavingsOption(
                label="Save 10%",
                amount=round(suggested_amount * 0.9, 2),
                savings_percentage=10,
            ),
            SavingsOption(
                label="Save 20%",
                amount=round(suggested_amount * 0.8, 2),
                savings_percentage=20,
            ),
        ]

        return BudgetSuggestionResponse(
            suggested_amount=suggested_amount,
            based_on_months=num_months,
            average_monthly_spend=round(average_monthly_spend, 2),
            category_breakdown=category_breakdown,
            savings_options=savings_options,
        )

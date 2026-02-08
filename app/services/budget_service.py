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
from app.schemas.budget_ai import (
    SimpleBudgetSuggestionResponse,
    RecommendedBudget,
    SimpleCategoryAllocation,
)
from app.services.split_aware_calculation import SplitAwareCalculation
from app.services.category_registry import get_category_registry


class BudgetService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.split_calc = SplitAwareCalculation(db)

    async def get_current_month_spend(self, user_id: str) -> float:
        """Get total spending for the current month (split-adjusted).

        For transactions that are part of expense splits, only the user's
        portion is counted. For non-split transactions, the full amount is used.
        """
        today = date.today()
        first_day = today.replace(day=1)

        # Get all transactions for the current month
        result = await self.db.execute(
            select(Transaction).where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= first_day,
                    Transaction.date <= today,
                )
            )
        )
        transactions = list(result.scalars().all())

        if not transactions:
            return 0.0

        # Calculate split-adjusted total
        return await self.split_calc.calculate_split_adjusted_spend(user_id, transactions)

    async def get_current_month_spend_by_category(
        self, user_id: str
    ) -> dict[str, float]:
        """Get spending by category for the current month (split-adjusted).

        For transactions that are part of expense splits, only the user's
        portion is counted. For non-split transactions, the full amount is used.
        """
        today = date.today()
        first_day = today.replace(day=1)

        # Get all transactions for the current month
        result = await self.db.execute(
            select(Transaction).where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= first_day,
                    Transaction.date <= today,
                )
            )
        )
        transactions = list(result.scalars().all())

        if not transactions:
            return {}

        # Calculate split-adjusted totals by category
        return await self.split_calc.calculate_split_adjusted_spend_by_category(user_id, transactions)

    async def get_historical_category_percentages(
        self, user_id: str, months: int = 3
    ) -> dict[str, float]:
        """Get historical spending percentages by category (split-adjusted).

        Returns a dict mapping category display names to their percentage of total spend.
        For transactions that are part of expense splits, only the user's portion is counted.
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

        # Get all transactions in the period
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

        # Calculate split-adjusted total spend
        total_spend = await self.split_calc.calculate_split_adjusted_spend(user_id, transactions)

        if total_spend == 0:
            return {}

        # Calculate split-adjusted spend by category
        category_spend = await self.split_calc.calculate_split_adjusted_spend_by_category(
            user_id, transactions
        )

        return {
            category: spent / total_spend
            for category, spent in category_spend.items()
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

                # Get category_id from registry
                registry = get_category_registry()
                category_id = registry.get_category_id(category_name)

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

                # Get category_id from registry
                registry = get_category_registry()
                category_id = registry.get_category_id(category_name)

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
        """Generate a smart budget suggestion based on historical spending (split-adjusted).

        For transactions that are part of expense splits, only the user's portion is counted.
        """
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

        # Get all transactions for the period
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
            return None

        # Get transaction amounts adjusted for splits
        tx_amounts = await self.split_calc.get_transaction_user_amounts(user_id, transactions)

        # Calculate monthly totals (split-adjusted)
        monthly_spend: dict = defaultdict(float)
        for tx, amount in tx_amounts:
            month_key = tx.date.replace(day=1)
            monthly_spend[month_key] += amount

        if not monthly_spend:
            return None

        # Calculate average monthly spend
        total_spend = sum(monthly_spend.values())
        num_months = len(monthly_spend)
        average_monthly_spend = total_spend / num_months

        # Calculate category totals (split-adjusted)
        category_totals: dict = defaultdict(float)
        for tx, amount in tx_amounts:
            category_totals[tx.category] += amount

        # Calculate category breakdown
        category_breakdown: List[CategoryBreakdown] = []
        for category_name, total_spent in category_totals.items():
            average_spend = total_spent / num_months
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

    async def get_simple_budget_suggestion(
        self, user_id: str, months: int = 3, target_amount: float | None = None
    ) -> SimpleBudgetSuggestionResponse:
        """Generate a simple budget suggestion based on historical spending.

        No AI involved - uses pure mathematical calculations.

        Args:
            user_id: The user's ID
            months: Number of months to analyze (default 3)
            target_amount: Optional target budget amount. If provided, category
                          allocations are scaled to fit this target.

        Returns:
            SimpleBudgetSuggestionResponse with recommended budget and category allocations
        """
        today = date.today()

        # Calculate the date range for the last N complete months
        end_date = today.replace(day=1)  # First day of current month (exclusive)

        year = end_date.year
        month = end_date.month - months
        while month <= 0:
            month += 12
            year -= 1
        start_date = date(year, month, 1)

        # Get all transactions for the period
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

        # Determine actual months with data
        if transactions:
            tx_amounts = await self.split_calc.get_transaction_user_amounts(user_id, transactions)
            monthly_spend: dict = defaultdict(float)
            for tx, amount in tx_amounts:
                month_key = tx.date.replace(day=1)
                monthly_spend[month_key] += amount

            num_months = len(monthly_spend)
            total_spend = sum(monthly_spend.values())
            average_monthly_spend = total_spend / num_months if num_months > 0 else 0

            # Calculate category totals
            category_totals: dict = defaultdict(float)
            for tx, amount in tx_amounts:
                category_totals[tx.category] += amount
        else:
            # No data - provide default values
            num_months = 0
            total_spend = 0
            average_monthly_spend = 0
            category_totals = {}

        # Determine confidence based on months of data
        if num_months >= 3:
            confidence = "high"
            reasoning = f"Based on {num_months} months of consistent spending data."
        elif num_months >= 1:
            confidence = "medium"
            reasoning = f"Based on {num_months} month{'s' if num_months > 1 else ''} of spending data. More data will improve accuracy."
        else:
            confidence = "low"
            # Provide Belgian household average as starting point
            average_monthly_spend = 400  # Default Belgian household average
            reasoning = "Suggested starting point based on typical household spending. Scan receipts to personalize."

        # Calculate recommended budget (10% below average for savings target)
        if target_amount:
            recommended_amount = target_amount
        else:
            recommended_amount = round(average_monthly_spend * 0.9 / 5) * 5  # Round to nearest €5

        # Ensure minimum budget
        recommended_amount = max(100, recommended_amount)

        # Calculate category allocations
        category_allocations: List[SimpleCategoryAllocation] = []

        if category_totals and num_months > 0:
            # Use actual spending patterns
            for category_name, total_spent in sorted(
                category_totals.items(), key=lambda x: x[1], reverse=True
            ):
                avg_spend = total_spent / num_months
                percentage = (avg_spend / average_monthly_spend * 100) if average_monthly_spend > 0 else 0

                # Scale to target/recommended amount
                if target_amount:
                    scaled_amount = (percentage / 100) * target_amount
                else:
                    scaled_amount = (percentage / 100) * recommended_amount

                category_allocations.append(
                    SimpleCategoryAllocation(
                        category=category_name,
                        suggested_amount=round(scaled_amount, 2),
                        percentage=round(percentage, 1),
                    )
                )
        else:
            # No data - provide default Belgian household breakdown
            # Names must match sub-categories in categories.csv exactly
            default_categories = [
                ("Pantry Staples (Pasta/Rice/Oil)", 14.0),
                ("Meat Poultry & Seafood", 13.0),
                ("Beverages (Non-Alcoholic)", 12.0),
                ("Fresh Produce (Fruit & Veg)", 11.0),
                ("Dairy Cheese & Eggs", 10.0),
                ("Snacks & Candy", 10.0),
                ("Household Consumables (Paper/Cleaning)", 9.0),
                ("Bakery & Bread", 8.0),
                ("Personal Hygiene (Soap/Shampoo)", 5.0),
                ("Frozen Foods", 4.0),
                ("Other", 4.0),
            ]
            for category_name, pct in default_categories:
                amount = (pct / 100) * recommended_amount
                category_allocations.append(
                    SimpleCategoryAllocation(
                        category=category_name,
                        suggested_amount=round(amount, 2),
                        percentage=pct,
                    )
                )

        return SimpleBudgetSuggestionResponse(
            recommended_budget=RecommendedBudget(
                amount=recommended_amount,
                confidence=confidence,
                reasoning=reasoning,
            ),
            category_allocations=category_allocations,
            based_on_months=num_months,
            total_spend_analyzed=round(total_spend, 2) if transactions else 0,
        )

import calendar
from datetime import date
from typing import List

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cached
from app.models.transaction import Transaction
from app.models.budget import Budget
from app.schemas.budget import (
    BudgetResponse,
    BudgetProgressResponse,
    CategoryProgress,
    CategoryAllocation,
)
from app.services.split_aware_calculation import SplitAwareCalculation
from app.services.category_registry import get_category_registry


class BudgetService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.split_calc = SplitAwareCalculation(db)

    @cached(include_month=True)
    async def get_current_month_spend(self, user_id: str) -> float:
        """Get total spending for the current month (split-adjusted)."""
        today = date.today()
        first_day = today.replace(day=1)

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

        return await self.split_calc.calculate_split_adjusted_spend(user_id, transactions)

    @cached(include_month=True)
    async def get_current_month_spend_by_category(
        self, user_id: str
    ) -> dict[str, float]:
        """Get spending by category for the current month (split-adjusted)."""
        today = date.today()
        first_day = today.replace(day=1)

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

        return await self.split_calc.calculate_split_adjusted_spend_by_category(user_id, transactions)

    async def get_budget_progress(
        self, user_id: str, budget: Budget
    ) -> BudgetProgressResponse:
        """Calculate budget progress with category guardrails.

        Category progress only includes categories that have explicit targets.
        Categories without targets are not shown — they still count toward
        the overall monthly spend but have no individual limit.
        """
        today = date.today()

        current_spend = await self.get_current_month_spend(user_id)
        spend_by_category = await self.get_current_month_spend_by_category(user_id)

        days_elapsed = today.day
        days_in_month = calendar.monthrange(today.year, today.month)[1]

        category_progress: List[CategoryProgress] = []
        registry = get_category_registry()

        if budget.category_allocations:
            for alloc in budget.category_allocations:
                category_name = alloc.get("category", "")
                limit_amount = alloc.get("amount", 0)
                spent_amount = spend_by_category.get(category_name, 0)

                is_over_budget = spent_amount > limit_amount
                over_budget_amount = round(spent_amount - limit_amount, 2) if is_over_budget else None

                category_id = registry.get_category_id(category_name)

                category_progress.append(
                    CategoryProgress(
                        category_id=category_id,
                        name=category_name,
                        limit_amount=limit_amount,
                        spent_amount=spent_amount,
                        is_over_budget=is_over_budget,
                        over_budget_amount=over_budget_amount,
                    )
                )

            # Sort by spent_amount descending
            category_progress.sort(key=lambda x: x.spent_amount, reverse=True)

        budget_response = BudgetResponse(
            id=budget.id,
            user_id=budget.user_id,
            monthly_amount=budget.monthly_amount,
            category_allocations=[
                CategoryAllocation(category=alloc.get("category", ""), amount=alloc.get("amount", 0))
                for alloc in (budget.category_allocations or [])
            ]
            if budget.category_allocations
            else None,
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

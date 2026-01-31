from datetime import datetime
from typing import Optional, List, Any

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.budget import Budget


class BudgetRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_user_id(self, user_id: str) -> Optional[Budget]:
        """Get budget by user ID."""
        result = await self.db.execute(
            select(Budget).where(Budget.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, budget_id: str) -> Optional[Budget]:
        """Get budget by ID."""
        result = await self.db.execute(
            select(Budget).where(Budget.id == budget_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_and_user(
        self, budget_id: str, user_id: str
    ) -> Optional[Budget]:
        """Get budget by ID and user ID."""
        result = await self.db.execute(
            select(Budget).where(
                Budget.id == budget_id,
                Budget.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        user_id: str,
        monthly_amount: float,
        category_allocations: Optional[List[Any]] = None,
        notifications_enabled: bool = True,
        alert_thresholds: Optional[List[float]] = None,
    ) -> Budget:
        """Create a new budget."""
        if alert_thresholds is None:
            alert_thresholds = [0.5, 0.75, 0.9]

        budget = Budget(
            user_id=user_id,
            monthly_amount=monthly_amount,
            category_allocations=category_allocations,
            notifications_enabled=notifications_enabled,
            alert_thresholds=alert_thresholds,
        )
        self.db.add(budget)
        await self.db.flush()
        await self.db.refresh(budget)
        return budget

    async def update(
        self,
        budget: Budget,
        monthly_amount: Optional[float] = None,
        category_allocations: Optional[List[Any]] = None,
        notifications_enabled: Optional[bool] = None,
        alert_thresholds: Optional[List[float]] = None,
        clear_category_allocations: bool = False,
        clear_alert_thresholds: bool = False,
    ) -> Budget:
        """Update an existing budget.

        Use clear_category_allocations=True to explicitly set category_allocations to None.
        Use clear_alert_thresholds=True to explicitly set alert_thresholds to None.
        """
        if monthly_amount is not None:
            budget.monthly_amount = monthly_amount
        if category_allocations is not None:
            budget.category_allocations = category_allocations
        elif clear_category_allocations:
            budget.category_allocations = None
        if notifications_enabled is not None:
            budget.notifications_enabled = notifications_enabled
        if alert_thresholds is not None:
            budget.alert_thresholds = alert_thresholds
        elif clear_alert_thresholds:
            budget.alert_thresholds = None

        # Update the updated_at timestamp
        budget.updated_at = datetime.utcnow()

        await self.db.flush()
        await self.db.refresh(budget)
        return budget

    async def delete(self, budget_id: str) -> bool:
        """Delete a budget."""
        budget = await self.get_by_id(budget_id)
        if not budget:
            return False

        await self.db.delete(budget)
        await self.db.flush()
        return True

    async def delete_by_user_id(self, user_id: str) -> bool:
        """Delete budget by user ID."""
        result = await self.db.execute(
            delete(Budget).where(Budget.user_id == user_id)
        )
        await self.db.flush()
        return result.rowcount > 0

    async def upsert(
        self,
        user_id: str,
        monthly_amount: float,
        category_allocations: Optional[List[Any]] = None,
        notifications_enabled: bool = True,
        alert_thresholds: Optional[List[float]] = None,
    ) -> Budget:
        """Create or replace budget for a user."""
        # Delete existing budget if any
        await self.delete_by_user_id(user_id)

        # Create new budget
        return await self.create(
            user_id=user_id,
            monthly_amount=monthly_amount,
            category_allocations=category_allocations,
            notifications_enabled=notifications_enabled,
            alert_thresholds=alert_thresholds,
        )

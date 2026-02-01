from datetime import datetime
from typing import Optional, List, Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget_history import BudgetHistory


class BudgetHistoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_user_id(self, user_id: str) -> List[BudgetHistory]:
        """Get all budget history entries for a user, ordered by month DESC."""
        result = await self.db.execute(
            select(BudgetHistory)
            .where(BudgetHistory.user_id == user_id)
            .order_by(BudgetHistory.month.desc())
        )
        return list(result.scalars().all())

    async def get_by_user_and_month(
        self, user_id: str, month: str
    ) -> Optional[BudgetHistory]:
        """Get budget history entry for a specific user and month."""
        result = await self.db.execute(
            select(BudgetHistory).where(
                BudgetHistory.user_id == user_id,
                BudgetHistory.month == month,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        user_id: str,
        monthly_amount: float,
        month: str,
        was_smart_budget: bool,
        category_allocations: Optional[List[Any]] = None,
        was_deleted: bool = False,
        notifications_enabled: bool = True,
        alert_thresholds: Optional[List[float]] = None,
    ) -> BudgetHistory:
        """Create a new budget history entry."""
        if alert_thresholds is None:
            alert_thresholds = [0.5, 0.75, 0.9]

        history = BudgetHistory(
            user_id=user_id,
            monthly_amount=monthly_amount,
            category_allocations=category_allocations,
            month=month,
            was_smart_budget=was_smart_budget,
            was_deleted=was_deleted,
            notifications_enabled=notifications_enabled,
            alert_thresholds=alert_thresholds,
        )
        self.db.add(history)
        await self.db.flush()
        await self.db.refresh(history)
        return history

    async def upsert(
        self,
        user_id: str,
        monthly_amount: float,
        month: str,
        was_smart_budget: bool,
        category_allocations: Optional[List[Any]] = None,
        was_deleted: bool = False,
        notifications_enabled: bool = True,
        alert_thresholds: Optional[List[float]] = None,
    ) -> BudgetHistory:
        """Create or update a budget history entry for a user and month."""
        existing = await self.get_by_user_and_month(user_id, month)

        if existing:
            # Update existing entry
            existing.monthly_amount = monthly_amount
            existing.category_allocations = category_allocations
            existing.was_smart_budget = was_smart_budget
            existing.was_deleted = was_deleted
            existing.notifications_enabled = notifications_enabled
            existing.alert_thresholds = alert_thresholds
            await self.db.flush()
            await self.db.refresh(existing)
            return existing
        else:
            # Create new entry
            return await self.create(
                user_id=user_id,
                monthly_amount=monthly_amount,
                month=month,
                was_smart_budget=was_smart_budget,
                category_allocations=category_allocations,
                was_deleted=was_deleted,
                notifications_enabled=notifications_enabled,
                alert_thresholds=alert_thresholds,
            )

    async def mark_as_deleted(self, user_id: str, month: str) -> bool:
        """Mark a budget history entry as deleted."""
        result = await self.db.execute(
            update(BudgetHistory)
            .where(
                BudgetHistory.user_id == user_id,
                BudgetHistory.month == month,
            )
            .values(was_deleted=True)
        )
        await self.db.flush()
        return result.rowcount > 0

    async def update(
        self,
        history: BudgetHistory,
        monthly_amount: Optional[float] = None,
        category_allocations: Optional[List[Any]] = None,
        was_smart_budget: Optional[bool] = None,
        was_deleted: Optional[bool] = None,
        notifications_enabled: Optional[bool] = None,
        alert_thresholds: Optional[List[float]] = None,
        clear_category_allocations: bool = False,
        clear_alert_thresholds: bool = False,
    ) -> BudgetHistory:
        """Update an existing budget history entry."""
        if monthly_amount is not None:
            history.monthly_amount = monthly_amount
        if category_allocations is not None:
            history.category_allocations = category_allocations
        elif clear_category_allocations:
            history.category_allocations = None
        if was_smart_budget is not None:
            history.was_smart_budget = was_smart_budget
        if was_deleted is not None:
            history.was_deleted = was_deleted
        if notifications_enabled is not None:
            history.notifications_enabled = notifications_enabled
        if alert_thresholds is not None:
            history.alert_thresholds = alert_thresholds
        elif clear_alert_thresholds:
            history.alert_thresholds = None

        await self.db.flush()
        await self.db.refresh(history)
        return history

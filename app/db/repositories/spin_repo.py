from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.spin import SpinTransaction, SpinBudget
from app.models.enums import SpinType


class SpinRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_spin_transaction(
        self,
        user_id: str,
        segment_index: int,
        segment_label: str,
        segment_type: str,
        cash_value: float,
        is_jackpot: bool,
        is_doubled: bool,
        points_value: int = 0,
        spin_type: Optional[SpinType] = None,
    ) -> SpinTransaction:
        txn = SpinTransaction(
            user_id=user_id,
            segment_index=segment_index,
            segment_label=segment_label,
            segment_type=segment_type,
            cash_value=cash_value,
            is_jackpot=is_jackpot,
            is_doubled=is_doubled,
            points_value=points_value,
            spin_type=spin_type,
        )
        self.db.add(txn)
        await self.db.flush()
        return txn

    async def get_user_spin_history(
        self, user_id: str, limit: int = 20
    ) -> list[SpinTransaction]:
        result = await self.db.execute(
            select(SpinTransaction)
            .where(SpinTransaction.user_id == user_id)
            .order_by(SpinTransaction.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_budget(self, cash_spent: float) -> None:
        """Update the global spin budget tracker."""
        result = await self.db.execute(select(SpinBudget))
        budget = result.scalar_one_or_none()
        if budget is None:
            budget = SpinBudget(
                total_budget=1500.0,
                total_spent=cash_spent,
                total_spins=1,
            )
            self.db.add(budget)
        else:
            await self.db.execute(
                update(SpinBudget)
                .where(SpinBudget.id == budget.id)
                .values(
                    total_spent=SpinBudget.total_spent + cash_spent,
                    total_spins=SpinBudget.total_spins + 1,
                )
            )
        await self.db.flush()

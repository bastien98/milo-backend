from typing import Optional

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cashback import CashbackTransaction, CashbackBalance
from app.models.enums import CashbackStatus


class CashbackRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_cashback_transaction(
        self,
        user_id: str,
        receipt_id: str,
        receipt_total: float,
        cashback_amount: float,
        effective_rate: float,
    ) -> CashbackTransaction:
        txn = CashbackTransaction(
            user_id=user_id,
            receipt_id=receipt_id,
            receipt_total=receipt_total,
            cashback_amount=cashback_amount,
            effective_rate=effective_rate,
            status=CashbackStatus.CONFIRMED,
        )
        self.db.add(txn)
        await self.db.flush()
        await self.db.refresh(txn)
        return txn

    async def get_cashback_transaction_by_receipt(
        self, receipt_id: str
    ) -> Optional[CashbackTransaction]:
        result = await self.db.execute(
            select(CashbackTransaction).where(
                CashbackTransaction.receipt_id == receipt_id
            )
        )
        return result.scalar_one_or_none()

    async def get_user_cashback_transactions(
        self, user_id: str, page: int = 1, page_size: int = 20
    ) -> tuple[list[CashbackTransaction], int]:
        # Count total
        count_result = await self.db.execute(
            select(func.count()).where(CashbackTransaction.user_id == user_id)
        )
        total = count_result.scalar() or 0

        # Fetch paginated, newest first
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(CashbackTransaction)
            .where(CashbackTransaction.user_id == user_id)
            .order_by(CashbackTransaction.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        transactions = list(result.scalars().all())
        return transactions, total

    async def get_or_create_balance(self, user_id: str) -> CashbackBalance:
        result = await self.db.execute(
            select(CashbackBalance).where(CashbackBalance.user_id == user_id)
        )
        balance = result.scalar_one_or_none()
        if balance is None:
            balance = CashbackBalance(
                user_id=user_id,
                total_earned=0.0,
                total_paid_out=0.0,
                current_balance=0.0,
            )
            self.db.add(balance)
            await self.db.flush()
            await self.db.refresh(balance)
        return balance

    async def update_balance_atomic(
        self, user_id: str, cashback_amount: float
    ) -> CashbackBalance:
        """Atomic increment of balance — no read-then-write race condition."""
        await self.db.execute(
            update(CashbackBalance)
            .where(CashbackBalance.user_id == user_id)
            .values(
                total_earned=CashbackBalance.total_earned + cashback_amount,
                current_balance=CashbackBalance.current_balance + cashback_amount,
            )
        )
        await self.db.flush()
        # Re-fetch to return updated state
        result = await self.db.execute(
            select(CashbackBalance).where(CashbackBalance.user_id == user_id)
        )
        return result.scalar_one()

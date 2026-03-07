from typing import Optional

from sqlalchemy import select, func, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
        spins_awarded: int = 0,
        status: CashbackStatus = CashbackStatus.PENDING,
    ) -> CashbackTransaction:
        txn = CashbackTransaction(
            user_id=user_id,
            receipt_id=receipt_id,
            receipt_total=receipt_total,
            cashback_amount=cashback_amount,
            effective_rate=effective_rate,
            spins_awarded=spins_awarded,
            status=status,
        )
        self.db.add(txn)
        await self.db.flush()
        return txn

    async def confirm_transaction(self, receipt_id: str) -> None:
        """Mark a PENDING transaction as CONFIRMED."""
        await self.db.execute(
            update(CashbackTransaction)
            .where(CashbackTransaction.receipt_id == receipt_id)
            .values(status=CashbackStatus.CONFIRMED)
        )
        await self.db.flush()

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

        # Fetch paginated, newest first — eagerly load receipt to avoid N+1
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(CashbackTransaction)
            .options(selectinload(CashbackTransaction.receipt))
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
        return balance

    async def upsert_balance_increment(
        self, user_id: str, cashback_amount: float
    ) -> None:
        """Insert or atomically increment balance in a single statement."""
        import uuid
        stmt = pg_insert(CashbackBalance).values(
            id=str(uuid.uuid4()),
            user_id=user_id,
            total_earned=cashback_amount,
            total_paid_out=0.0,
            current_balance=cashback_amount,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "total_earned": CashbackBalance.total_earned + cashback_amount,
                "current_balance": CashbackBalance.current_balance + cashback_amount,
            },
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def add_spins(self, user_id: str, spins: int) -> None:
        """Atomically add spins to user's balance."""
        if spins <= 0:
            return
        await self.get_or_create_balance(user_id)
        await self.db.execute(
            update(CashbackBalance)
            .where(CashbackBalance.user_id == user_id)
            .values(spins_available=CashbackBalance.spins_available + spins)
        )
        await self.db.flush()

    async def consume_spin(self, user_id: str) -> bool:
        """Atomically consume 1 spin. Returns False if no spins available."""
        result = await self.db.execute(
            update(CashbackBalance)
            .where(
                CashbackBalance.user_id == user_id,
                CashbackBalance.spins_available > 0,
            )
            .values(spins_available=CashbackBalance.spins_available - 1)
        )
        await self.db.flush()
        return result.rowcount > 0

import uuid
from typing import Optional

from sqlalchemy import select, func, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.cashback import CashbackTransaction, CashbackBalance
from app.models.enums import CashbackStatus, SpinType


class CashbackRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_cashback_transaction(
        self,
        user_id: str,
        receipt_id: str,
        receipt_total: float,
        # New points fields
        points_total: int = 0,
        fixed_points: int = 0,
        grote_kar_points: int = 0,
        kickstart_bonus_points: int = 0,
        spin_type: Optional[SpinType] = None,
        is_kickstart: bool = False,
        is_streak_saver: bool = False,
        # Legacy fields (kept for compat)
        cashback_amount: float = 0.0,
        effective_rate: float = 0.0,
        spins_awarded: int = 0,
        status: CashbackStatus = CashbackStatus.PENDING,
    ) -> CashbackTransaction:
        txn = CashbackTransaction(
            user_id=user_id,
            receipt_id=receipt_id,
            receipt_total=receipt_total,
            points_total=points_total,
            fixed_points=fixed_points,
            grote_kar_points=grote_kar_points,
            kickstart_bonus_points=kickstart_bonus_points,
            spin_type=spin_type,
            is_kickstart=is_kickstart,
            is_streak_saver=is_streak_saver,
            cashback_amount=cashback_amount,
            effective_rate=effective_rate,
            spins_awarded=spins_awarded,
            status=status,
        )
        self.db.add(txn)
        await self.db.flush()
        return txn

    async def confirm_transaction(self, receipt_id: str) -> None:
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
        count_result = await self.db.execute(
            select(func.count()).where(CashbackTransaction.user_id == user_id)
        )
        total = count_result.scalar() or 0

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
            try:
                balance = CashbackBalance(
                    user_id=user_id,
                    total_earned=0.0,
                    total_paid_out=0.0,
                    current_balance=0.0,
                    points_balance=0,
                    total_points_earned=0,
                    total_points_paid_out=0,
                    standard_spins=0,
                    premium_spins=0,
                )
                self.db.add(balance)
                await self.db.flush()
            except IntegrityError:
                await self.db.rollback()
                result = await self.db.execute(
                    select(CashbackBalance).where(CashbackBalance.user_id == user_id)
                )
                balance = result.scalar_one()
        return balance

    async def upsert_points_increment(self, user_id: str, points: int) -> None:
        """Insert or atomically increment points balance in a single statement."""
        stmt = pg_insert(CashbackBalance).values(
            id=str(uuid.uuid4()),
            user_id=user_id,
            points_balance=points,
            total_points_earned=points,
            total_points_paid_out=0,
            standard_spins=0,
            premium_spins=0,
            total_earned=0.0,
            total_paid_out=0.0,
            current_balance=0.0,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "points_balance": CashbackBalance.points_balance + points,
                "total_points_earned": CashbackBalance.total_points_earned + points,
            },
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def add_standard_spins(self, user_id: str, spins: int) -> None:
        if spins <= 0:
            return
        await self.get_or_create_balance(user_id)
        await self.db.execute(
            update(CashbackBalance)
            .where(CashbackBalance.user_id == user_id)
            .values(standard_spins=CashbackBalance.standard_spins + spins)
        )
        await self.db.flush()

    async def add_premium_spins(self, user_id: str, spins: int) -> None:
        if spins <= 0:
            return
        await self.get_or_create_balance(user_id)
        await self.db.execute(
            update(CashbackBalance)
            .where(CashbackBalance.user_id == user_id)
            .values(premium_spins=CashbackBalance.premium_spins + spins)
        )
        await self.db.flush()

    async def consume_standard_spin(self, user_id: str) -> bool:
        result = await self.db.execute(
            update(CashbackBalance)
            .where(
                CashbackBalance.user_id == user_id,
                CashbackBalance.standard_spins > 0,
            )
            .values(standard_spins=CashbackBalance.standard_spins - 1)
        )
        await self.db.flush()
        return result.rowcount > 0

    async def consume_premium_spin(self, user_id: str) -> bool:
        result = await self.db.execute(
            update(CashbackBalance)
            .where(
                CashbackBalance.user_id == user_id,
                CashbackBalance.premium_spins > 0,
            )
            .values(premium_spins=CashbackBalance.premium_spins - 1)
        )
        await self.db.flush()
        return result.rowcount > 0

    # ── Legacy methods kept for backward compat ──────────────────────────

    async def upsert_balance_increment(self, user_id: str, cashback_amount: float) -> None:
        """Legacy euro balance increment. Kept for backward compat."""
        stmt = pg_insert(CashbackBalance).values(
            id=str(uuid.uuid4()),
            user_id=user_id,
            total_earned=cashback_amount,
            total_paid_out=0.0,
            current_balance=cashback_amount,
            points_balance=0,
            total_points_earned=0,
            total_points_paid_out=0,
            standard_spins=0,
            premium_spins=0,
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
        """Legacy: add standard spins."""
        await self.add_standard_spins(user_id, spins)

    async def consume_spin(self, user_id: str) -> bool:
        """Legacy: consume a standard spin."""
        return await self.consume_standard_spin(user_id)

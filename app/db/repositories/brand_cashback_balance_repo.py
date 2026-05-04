import uuid

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brand_cashback_balance import BrandCashbackBalance


class InsufficientBalanceError(Exception):
    """Raised when a debit would take balance_cents below zero."""

    def __init__(self, user_id: str, balance_cents: int, requested_cents: int):
        super().__init__(
            f"Insufficient balance for user {user_id}: "
            f"have {balance_cents} cents, requested {requested_cents}"
        )
        self.balance_cents = balance_cents
        self.requested_cents = requested_cents


class BrandCashbackBalanceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_balance(self, user_id: str) -> BrandCashbackBalance:
        """Read-only fetch. Returns a transient zero-balance object if no row exists yet
        (so callers don't have to special-case fresh users on read paths).
        """
        result = await self.db.execute(
            select(BrandCashbackBalance).where(BrandCashbackBalance.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            return row
        return BrandCashbackBalance(
            id="",
            user_id=user_id,
            balance_cents=0,
            total_earned_cents=0,
            total_withdrawn_cents=0,
        )

    async def credit(self, user_id: str, amount_cents: int) -> None:
        """Atomic upsert + increment. No-op for non-positive amounts."""
        if amount_cents <= 0:
            return
        stmt = pg_insert(BrandCashbackBalance).values(
            id=str(uuid.uuid4()),
            user_id=user_id,
            balance_cents=amount_cents,
            total_earned_cents=amount_cents,
            total_withdrawn_cents=0,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "balance_cents": BrandCashbackBalance.balance_cents + amount_cents,
                "total_earned_cents": BrandCashbackBalance.total_earned_cents + amount_cents,
            },
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def debit(self, user_id: str, amount_cents: int) -> None:
        """Atomic decrement. Raises InsufficientBalanceError if balance_cents would
        go negative. The single conditional UPDATE prevents lost updates under
        concurrent debits without needing an explicit row lock.
        """
        if amount_cents <= 0:
            return
        result = await self.db.execute(
            update(BrandCashbackBalance)
            .where(
                BrandCashbackBalance.user_id == user_id,
                BrandCashbackBalance.balance_cents >= amount_cents,
            )
            .values(
                balance_cents=BrandCashbackBalance.balance_cents - amount_cents,
                total_withdrawn_cents=BrandCashbackBalance.total_withdrawn_cents
                + amount_cents,
            )
        )
        if (result.rowcount or 0) == 0:
            current = await self.get_balance(user_id)
            raise InsufficientBalanceError(
                user_id, current.balance_cents, amount_cents
            )
        await self.db.flush()

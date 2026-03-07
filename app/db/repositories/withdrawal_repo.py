import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.withdrawal import WithdrawalRequest
from app.models.enums import WithdrawalStatus
from app.models.cashback import CashbackBalance


class WithdrawalRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_withdrawal(
        self,
        user_id: str,
        amount: float,
        iban: str,
        iban_last4: str,
        status: WithdrawalStatus,
        fraud_check_passed: bool,
        fraud_check_details: Optional[dict] = None,
    ) -> WithdrawalRequest:
        withdrawal = WithdrawalRequest(
            id=str(uuid.uuid4()),
            user_id=user_id,
            amount=amount,
            iban=iban,
            iban_last4=iban_last4,
            status=status,
            fraud_check_passed=fraud_check_passed,
            fraud_check_details=fraud_check_details,
        )
        self.db.add(withdrawal)
        await self.db.flush()
        return withdrawal

    async def get_pending_by_user(self, user_id: str) -> Optional[WithdrawalRequest]:
        """Check if user has an active (non-terminal) withdrawal."""
        result = await self.db.execute(
            select(WithdrawalRequest).where(
                WithdrawalRequest.user_id == user_id,
                WithdrawalRequest.status.in_([
                    WithdrawalStatus.PENDING_REVIEW,
                    WithdrawalStatus.AUTO_APPROVED,
                    WithdrawalStatus.APPROVED,
                ]),
            )
        )
        return result.scalar_one_or_none()

    async def get_user_withdrawals(self, user_id: str) -> list[WithdrawalRequest]:
        result = await self.db.execute(
            select(WithdrawalRequest)
            .where(WithdrawalRequest.user_id == user_id)
            .order_by(WithdrawalRequest.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_last_paid_out(self, user_id: str) -> Optional[WithdrawalRequest]:
        """Get the most recent PAID_OUT withdrawal for cooldown checks."""
        result = await self.db.execute(
            select(WithdrawalRequest)
            .where(
                WithdrawalRequest.user_id == user_id,
                WithdrawalRequest.status == WithdrawalStatus.PAID_OUT,
            )
            .order_by(WithdrawalRequest.paid_out_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def has_previous_rejection(self, user_id: str) -> bool:
        result = await self.db.execute(
            select(WithdrawalRequest.id)
            .where(
                WithdrawalRequest.user_id == user_id,
                WithdrawalRequest.status == WithdrawalStatus.REJECTED,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_by_id(self, withdrawal_id: str) -> Optional[WithdrawalRequest]:
        result = await self.db.execute(
            select(WithdrawalRequest).where(WithdrawalRequest.id == withdrawal_id)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        withdrawal_id: str,
        status: WithdrawalStatus,
        admin_notes: Optional[str] = None,
        wise_transfer_id: Optional[str] = None,
    ) -> Optional[WithdrawalRequest]:
        values: dict = {"status": status}
        if admin_notes is not None:
            values["admin_notes"] = admin_notes
        if wise_transfer_id is not None:
            values["wise_transfer_id"] = wise_transfer_id
        if status in (WithdrawalStatus.APPROVED, WithdrawalStatus.REJECTED, WithdrawalStatus.AUTO_APPROVED):
            values["reviewed_at"] = datetime.now()
        if status == WithdrawalStatus.PAID_OUT:
            values["paid_out_at"] = datetime.now()

        await self.db.execute(
            update(WithdrawalRequest)
            .where(WithdrawalRequest.id == withdrawal_id)
            .values(**values)
        )
        await self.db.flush()
        return await self.get_by_id(withdrawal_id)

    async def get_all_pending(self) -> list[WithdrawalRequest]:
        """Get all pending withdrawals for admin review."""
        result = await self.db.execute(
            select(WithdrawalRequest)
            .options(selectinload(WithdrawalRequest.user))
            .where(WithdrawalRequest.status.in_([
                WithdrawalStatus.PENDING_REVIEW,
                WithdrawalStatus.AUTO_APPROVED,
            ]))
            .order_by(WithdrawalRequest.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_all_actionable(self) -> list[WithdrawalRequest]:
        """Get all withdrawals that need action (pending review, auto-approved, approved)."""
        result = await self.db.execute(
            select(WithdrawalRequest)
            .options(selectinload(WithdrawalRequest.user))
            .where(WithdrawalRequest.status.in_([
                WithdrawalStatus.PENDING_REVIEW,
                WithdrawalStatus.AUTO_APPROVED,
                WithdrawalStatus.APPROVED,
            ]))
            .order_by(WithdrawalRequest.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_all_withdrawals(self) -> list[WithdrawalRequest]:
        """Get all withdrawals across all users."""
        result = await self.db.execute(
            select(WithdrawalRequest)
            .options(selectinload(WithdrawalRequest.user))
            .order_by(WithdrawalRequest.created_at.desc())
        )
        return list(result.scalars().all())

    async def deduct_balance(self, user_id: str, amount: float) -> bool:
        """Atomically deduct amount from current_balance. Returns False if insufficient."""
        result = await self.db.execute(
            update(CashbackBalance)
            .where(
                CashbackBalance.user_id == user_id,
                CashbackBalance.current_balance >= amount,
            )
            .values(current_balance=CashbackBalance.current_balance - amount)
        )
        await self.db.flush()
        return result.rowcount > 0

    async def refund_balance(self, user_id: str, amount: float) -> None:
        """Refund amount back to current_balance (on rejection)."""
        await self.db.execute(
            update(CashbackBalance)
            .where(CashbackBalance.user_id == user_id)
            .values(current_balance=CashbackBalance.current_balance + amount)
        )
        await self.db.flush()

    async def mark_paid_out_balance(self, user_id: str, amount: float) -> None:
        """Increment total_paid_out when withdrawal is paid."""
        await self.db.execute(
            update(CashbackBalance)
            .where(CashbackBalance.user_id == user_id)
            .values(total_paid_out=CashbackBalance.total_paid_out + amount)
        )
        await self.db.flush()

    async def delete_user_withdrawals(self, user_id: str) -> int:
        """Delete all withdrawals for a user (test mode only)."""
        withdrawals = await self.get_user_withdrawals(user_id)
        count = len(withdrawals)
        for w in withdrawals:
            await self.db.delete(w)
        await self.db.flush()
        return count

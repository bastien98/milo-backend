import logging
import math
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.brand_cashback_balance_repo import (
    BrandCashbackBalanceRepository,
)
from app.db.repositories.withdrawal_repo import WithdrawalRepository
from app.models.enums import WithdrawalStatus
from app.models.receipt import Receipt
from app.models.enums import ReceiptStatus
from app.models.user import User
from app.models.user_profile import UserProfile
from app.models.withdrawal import WithdrawalRequest
from app.services.fraud_check_service import FraudCheckService
from app.services.wise_service import WiseService

logger = logging.getLogger(__name__)

VALID_AMOUNTS = [5.0, 10.0, 15.0, 20.0]
COOLDOWN_DAYS = 7
MIN_ACCOUNT_AGE_DAYS = 14
MIN_PROCESSED_RECEIPTS = 5
TEST_MODE = os.getenv("WITHDRAWAL_TEST_MODE", "false").lower() == "true"
TEST_IBAN = "BE00000000000000"


class WithdrawalService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = WithdrawalRepository(db)
        self.balance_repo = BrandCashbackBalanceRepository(db)
        self.fraud_service = FraudCheckService(db)
        self.wise_service = WiseService()

    @staticmethod
    def validate_iban(iban: str) -> bool:
        """IBAN validation with mod97 check."""
        cleaned = iban.replace(" ", "").upper()
        if len(cleaned) < 15 or len(cleaned) > 34:
            return False
        if not re.match(r"^[A-Z]{2}[0-9]{2}", cleaned):
            return False
        # Mod97 check
        rearranged = cleaned[4:] + cleaned[:4]
        numeric = ""
        for char in rearranged:
            if char.isdigit():
                numeric += char
            else:
                numeric += str(ord(char) - 55)
        return int(numeric) % 97 == 1

    async def _count_processed_receipts(self, user_id: str) -> int:
        """Receipts that completed OCR — fraud-eligibility signal that replaces the
        old confirmed-cashback count. Brand cashback earnings aren't required;
        the user just needs a real scan history."""
        result = await self.db.execute(
            select(func.count()).where(
                Receipt.user_id == user_id,
                Receipt.status == ReceiptStatus.COMPLETED,
            )
        )
        return result.scalar() or 0

    async def get_withdrawal_info(self, user: User) -> dict:
        """Get withdrawal eligibility info for the user."""
        balance = await self.balance_repo.get_balance(user.id)
        balance_cents = balance.balance_cents
        current_balance = round(balance_cents / 100, 2)

        max_withdrawable = math.floor(current_balance / 5) * 5.0
        available_amounts = [a for a in VALID_AMOUNTS if a <= max_withdrawable]

        pending = await self.repo.get_pending_by_user(user.id)
        has_pending = pending is not None

        processed_receipt_count = await self._count_processed_receipts(user.id)

        # Get last IBAN from profile
        profile = await self.db.execute(
            select(UserProfile).where(UserProfile.user_id == user.firebase_uid)
        )
        profile_row = profile.scalar_one_or_none()
        last_iban = profile_row.iban if profile_row else None
        last_iban_last4 = profile_row.iban_last4 if profile_row else None

        # Determine eligibility
        can_withdraw = True
        reason = None

        if has_pending:
            can_withdraw = False
            reason = "You already have a pending withdrawal"
        elif max_withdrawable < 5:
            can_withdraw = False
            reason = "Minimum withdrawal is €5"
        else:
            # Check cooldown (skip in test mode)
            if not TEST_MODE:
                last_paid = await self.repo.get_last_paid_out(user.id)
                if last_paid and last_paid.paid_out_at:
                    paid_at = last_paid.paid_out_at
                    if paid_at.tzinfo is None:
                        paid_at = paid_at.replace(tzinfo=timezone.utc)
                    cooldown_end = paid_at + timedelta(days=COOLDOWN_DAYS)
                    now = datetime.now(timezone.utc)
                    if now < cooldown_end:
                        can_withdraw = False
                        days_left = (cooldown_end - now).days + 1
                        reason = f"Cooldown active. Available in {days_left} day{'s' if days_left != 1 else ''}"

            # Check account age (skip in test mode)
            if can_withdraw and not TEST_MODE:
                if user.created_at:
                    created = user.created_at
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    age_days = (datetime.now(timezone.utc) - created).days
                    if age_days < MIN_ACCOUNT_AGE_DAYS:
                        can_withdraw = False
                        days_left = MIN_ACCOUNT_AGE_DAYS - age_days
                        reason = f"Account must be at least 14 days old. {days_left} day{'s' if days_left != 1 else ''} remaining"

            # Check minimum receipt count (skip in test mode)
            if can_withdraw and not TEST_MODE:
                if processed_receipt_count < MIN_PROCESSED_RECEIPTS:
                    can_withdraw = False
                    remaining = MIN_PROCESSED_RECEIPTS - processed_receipt_count
                    reason = f"Scan {remaining} more receipt{'s' if remaining != 1 else ''} to unlock withdrawals"

        # Build active withdrawal response
        active_withdrawal = None
        if pending:
            active_withdrawal = {
                "id": pending.id,
                "amount": pending.amount,
                "iban_last4": pending.iban_last4,
                "status": pending.status.value,
                "fraud_check_passed": pending.fraud_check_passed,
                "admin_notes": pending.admin_notes,
                "created_at": pending.created_at.isoformat() if pending.created_at else None,
                "reviewed_at": pending.reviewed_at.isoformat() if pending.reviewed_at else None,
                "paid_out_at": pending.paid_out_at.isoformat() if pending.paid_out_at else None,
            }

        return {
            "balance_cents": balance_cents,
            "current_balance": current_balance,
            "max_withdrawable": max_withdrawable,
            "available_amounts": available_amounts,
            "has_pending_withdrawal": has_pending,
            "active_withdrawal": active_withdrawal,
            "last_iban": last_iban,
            "last_iban_last4": last_iban_last4,
            "can_withdraw": can_withdraw,
            "cannot_withdraw_reason": reason,
            "processed_receipt_count": processed_receipt_count,
        }

    async def create_withdrawal(
        self, user: User, amount: float, iban: str
    ) -> dict:
        """Create a new withdrawal request."""
        # Validate amount
        if amount not in VALID_AMOUNTS:
            raise ValueError(f"Invalid amount. Must be one of: {VALID_AMOUNTS}")

        # Validate IBAN (skip for test IBAN in test mode)
        is_test_iban = TEST_MODE and iban.replace(" ", "").upper() == TEST_IBAN
        if not is_test_iban and not self.validate_iban(iban):
            raise ValueError("Invalid IBAN format")

        cleaned_iban = iban.replace(" ", "").upper()
        iban_last4 = cleaned_iban[-4:]

        # Check balance
        balance = await self.balance_repo.get_balance(user.id)
        current_balance_euros = round(balance.balance_cents / 100, 2)
        max_withdrawable = math.floor(current_balance_euros / 5) * 5.0
        if amount > max_withdrawable:
            raise ValueError("Insufficient balance")

        # Check no pending
        pending = await self.repo.get_pending_by_user(user.id)
        if pending:
            raise ValueError("You already have a pending withdrawal")

        # Check cooldown (skip in test mode)
        if not TEST_MODE:
            last_paid = await self.repo.get_last_paid_out(user.id)
            if last_paid and last_paid.paid_out_at:
                paid_at = last_paid.paid_out_at
                if paid_at.tzinfo is None:
                    paid_at = paid_at.replace(tzinfo=timezone.utc)
                cooldown_end = paid_at + timedelta(days=COOLDOWN_DAYS)
                if datetime.now(timezone.utc) < cooldown_end:
                    raise ValueError("Cooldown period active")

        # Check account age (skip in test mode)
        if not TEST_MODE and user.created_at:
            created = user.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - created).days < MIN_ACCOUNT_AGE_DAYS:
                raise ValueError("Account too new for withdrawals")

        # Save IBAN to profile
        profile = await self.db.execute(
            select(UserProfile).where(UserProfile.user_id == user.firebase_uid)
        )
        profile_row = profile.scalar_one_or_none()
        if profile_row:
            profile_row.iban = cleaned_iban
            profile_row.iban_last4 = iban_last4
            await self.db.flush()

        # Run fraud checks (skip entirely in test mode)
        if TEST_MODE:
            fraud_passed = True
            fraud_details = {"all_passed": True, "test_mode": True}
        else:
            fraud_passed, fraud_details = await self.fraud_service.run_checks(user.id)

        status = (
            WithdrawalStatus.AUTO_APPROVED if fraud_passed
            else WithdrawalStatus.PENDING_REVIEW
        )

        # Atomically deduct balance
        deducted = await self.repo.deduct_balance(user.id, amount)
        if not deducted:
            raise ValueError("Insufficient balance (concurrent modification)")

        # Create withdrawal request
        withdrawal = await self.repo.create_withdrawal(
            user_id=user.id,
            amount=amount,
            iban=cleaned_iban,
            iban_last4=iban_last4,
            status=status,
            fraud_check_passed=fraud_passed,
            fraud_check_details=fraud_details,
        )

        # If auto-approved, trigger Wise payout
        wise_transfer_id = None
        if status == WithdrawalStatus.AUTO_APPROVED:
            try:
                wise_transfer_id = await self.wise_service.create_payout(
                    iban=cleaned_iban,
                    amount=amount,
                    reference=f"MILO-{withdrawal.id[:8]}",
                )
                await self.repo.update_status(
                    withdrawal.id, WithdrawalStatus.AUTO_APPROVED,
                    wise_transfer_id=wise_transfer_id,
                )
            except Exception as e:
                logger.error(f"Wise payout failed for withdrawal {withdrawal.id}: {e}")
                # Keep as AUTO_APPROVED, admin can retry manually

        # Get new balance
        new_balance = await self.balance_repo.get_balance(user.id)

        return {
            "id": withdrawal.id,
            "amount": withdrawal.amount,
            "iban_last4": iban_last4,
            "status": status.value,
            "fraud_check_passed": fraud_passed,
            "fraud_check_details": fraud_details,
            "new_balance": round(new_balance.balance_cents / 100, 2),
            "new_balance_cents": new_balance.balance_cents,
        }

    async def approve_withdrawal(
        self, withdrawal_id: str, admin_notes: Optional[str] = None
    ) -> WithdrawalRequest:
        """Admin: approve a pending withdrawal and trigger Wise payout."""
        withdrawal = await self.repo.get_by_id(withdrawal_id)
        if not withdrawal:
            raise ValueError("Withdrawal not found")
        if withdrawal.status not in (WithdrawalStatus.PENDING_REVIEW, WithdrawalStatus.AUTO_APPROVED):
            raise ValueError(f"Cannot approve withdrawal in status {withdrawal.status.value}")

        # Trigger Wise payout
        try:
            wise_transfer_id = await self.wise_service.create_payout(
                iban=withdrawal.iban,
                amount=withdrawal.amount,
                reference=f"MILO-{withdrawal.id[:8]}",
            )
        except Exception as e:
            logger.error(f"Wise payout failed: {e}")
            raise ValueError(f"Payout failed: {e}")

        updated = await self.repo.update_status(
            withdrawal_id, WithdrawalStatus.APPROVED,
            admin_notes=admin_notes,
            wise_transfer_id=wise_transfer_id,
        )
        return updated

    async def mark_paid_out(self, withdrawal_id: str) -> WithdrawalRequest:
        """Admin: mark withdrawal as paid out."""
        withdrawal = await self.repo.get_by_id(withdrawal_id)
        if not withdrawal:
            raise ValueError("Withdrawal not found")
        if withdrawal.status not in (WithdrawalStatus.APPROVED, WithdrawalStatus.AUTO_APPROVED):
            raise ValueError(f"Cannot mark as paid from status {withdrawal.status.value}")

        await self.repo.mark_paid_out_balance(withdrawal.user_id, withdrawal.amount)
        updated = await self.repo.update_status(withdrawal_id, WithdrawalStatus.PAID_OUT)
        return updated

    async def reject_withdrawal(
        self, withdrawal_id: str, admin_notes: Optional[str] = None
    ) -> WithdrawalRequest:
        """Admin: reject withdrawal and refund balance."""
        withdrawal = await self.repo.get_by_id(withdrawal_id)
        if not withdrawal:
            raise ValueError("Withdrawal not found")
        if withdrawal.status in (WithdrawalStatus.PAID_OUT, WithdrawalStatus.REJECTED):
            raise ValueError(f"Cannot reject withdrawal in status {withdrawal.status.value}")

        # Refund balance
        await self.repo.refund_balance(withdrawal.user_id, withdrawal.amount)
        updated = await self.repo.update_status(
            withdrawal_id, WithdrawalStatus.REJECTED, admin_notes=admin_notes
        )
        return updated

    async def get_user_withdrawals(self, user_id: str) -> list[WithdrawalRequest]:
        return await self.repo.get_user_withdrawals(user_id)

    async def get_all_pending(self) -> list[WithdrawalRequest]:
        return await self.repo.get_all_pending()

    async def get_all_actionable(self) -> list[WithdrawalRequest]:
        return await self.repo.get_all_actionable()

    async def get_all_withdrawals(self) -> list[WithdrawalRequest]:
        return await self.repo.get_all_withdrawals()

    # Test mode helpers
    async def test_auto_process(self, withdrawal_id: str) -> WithdrawalRequest:
        """Test mode: auto-process through approve -> paid_out."""
        if not TEST_MODE:
            raise ValueError("Test mode is not enabled")
        withdrawal = await self.repo.get_by_id(withdrawal_id)
        if not withdrawal:
            raise ValueError("Withdrawal not found")

        # Approve
        await self.repo.update_status(
            withdrawal_id, WithdrawalStatus.APPROVED,
            wise_transfer_id=f"test-auto-{withdrawal_id[:8]}",
        )
        # Mark paid
        await self.repo.mark_paid_out_balance(withdrawal.user_id, withdrawal.amount)
        updated = await self.repo.update_status(withdrawal_id, WithdrawalStatus.PAID_OUT)
        return updated

    async def test_reset(self, user_id: str) -> int:
        """Test mode: delete all withdrawals and restore balances."""
        if not TEST_MODE:
            raise ValueError("Test mode is not enabled")
        withdrawals = await self.repo.get_user_withdrawals(user_id)
        # Refund any non-paid-out, non-rejected withdrawals
        for w in withdrawals:
            if w.status not in (WithdrawalStatus.PAID_OUT, WithdrawalStatus.REJECTED):
                await self.repo.refund_balance(user_id, w.amount)
        count = await self.repo.delete_user_withdrawals(user_id)
        return count

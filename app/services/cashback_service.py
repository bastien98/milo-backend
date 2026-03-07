import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.cashback_repo import CashbackRepository
from app.models.cashback import CashbackTransaction, CashbackBalance
from app.models.enums import CashbackStatus

logger = logging.getLogger(__name__)


class CashbackService:
    # Progressive tiers: (upper_bound, rate)
    # First 5 segments are €80, last segment is €100. Cap at €500.
    _TIERS = [
        (Decimal("80"), Decimal("0.0050")),    # €0–€80:   0.50%
        (Decimal("160"), Decimal("0.0060")),   # €80–€160:  0.60%
        (Decimal("240"), Decimal("0.0070")),   # €160–€240: 0.70%
        (Decimal("320"), Decimal("0.0080")),   # €240–€320: 0.80%
        (Decimal("400"), Decimal("0.0090")),   # €320–€400: 0.90%
        (Decimal("500"), Decimal("0.0100")),   # €400–€500: 1.00%
    ]
    _MAX_ELIGIBLE = Decimal("500")

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CashbackRepository(db)

    @staticmethod
    def calculate_cashback(total_amount: float) -> tuple[float, float]:
        """Pure function. Returns (cashback_amount, effective_rate).

        Uses Decimal arithmetic internally to avoid floating-point rounding errors.
        Applies progressive tiers and caps eligible spending at €500.
        """
        if total_amount <= 0:
            return 0.0, 0.0

        eligible = min(Decimal(str(total_amount)), CashbackService._MAX_ELIGIBLE)
        cashback = Decimal("0")
        prev_bound = Decimal("0")

        for upper_bound, rate in CashbackService._TIERS:
            if eligible <= prev_bound:
                break
            slice_ = min(eligible, upper_bound) - prev_bound
            cashback += slice_ * rate
            prev_bound = upper_bound

        cashback = float(cashback.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        effective_rate = round(cashback / total_amount, 6)
        return cashback, effective_rate

    @staticmethod
    def calculate_cashback_segments(total_amount: float) -> list[dict]:
        """Return segment breakdown for preview display."""
        if total_amount <= 0:
            return []

        eligible = min(Decimal(str(total_amount)), CashbackService._MAX_ELIGIBLE)
        segments = []
        prev_bound = Decimal("0")

        for i, (upper_bound, rate) in enumerate(CashbackService._TIERS):
            if eligible <= prev_bound:
                break
            slice_ = min(eligible, upper_bound) - prev_bound
            seg_cashback = slice_ * rate
            segments.append(
                {
                    "segment": i + 1,
                    "slice_start": float(prev_bound),
                    "slice_end": float(prev_bound + slice_),
                    "rate": float(rate),
                    "cashback": float(seg_cashback.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
                }
            )
            prev_bound = upper_bound

        return segments

    async def award_cashback_for_receipt(
        self,
        user_id: str,
        receipt_id: str,
        receipt_total: float,
    ) -> CashbackTransaction:
        """Create a PENDING cashback transaction for a completed receipt. Idempotent.

        The balance is NOT credited here. The user must explicitly tap "Tap to claim"
        in the app, which calls claim_cashback(), to move the transaction to CONFIRMED
        and credit the amount to their wallet.
        """
        from app.services.gold_tier_service import check_gold_tier, calculate_spins_for_receipt

        # Check idempotency — skip if already created
        existing = await self.repo.get_cashback_transaction_by_receipt(receipt_id)
        if existing:
            logger.info(f"Cashback transaction already exists for receipt {receipt_id}, skipping")
            return existing

        cashback_amount, effective_rate = self.calculate_cashback(receipt_total)

        # Determine Gold Tier status and spins
        is_gold = await check_gold_tier(self.db, user_id)
        spins_awarded = calculate_spins_for_receipt(receipt_total) if is_gold else 0

        # Create PENDING transaction — balance and spins are NOT credited yet.
        # They will be credited when the user claims via claim_cashback().
        txn = await self.repo.create_cashback_transaction(
            user_id=user_id,
            receipt_id=receipt_id,
            receipt_total=receipt_total,
            cashback_amount=cashback_amount,
            effective_rate=effective_rate,
            spins_awarded=spins_awarded,
            status=CashbackStatus.PENDING,
        )

        logger.info(
            f"Cashback pending (awaiting claim): receipt={receipt_id}, "
            f"total={receipt_total}, cashback={cashback_amount}, "
            f"rate={effective_rate}, spins={spins_awarded}, gold_tier={is_gold}"
        )
        return txn

    async def claim_cashback(
        self, user_id: str, receipt_id: str
    ) -> Optional[CashbackTransaction]:
        """Confirm a PENDING cashback transaction and credit the user's wallet.

        Idempotent: safe to call multiple times for the same receipt.
        Returns None if no transaction exists for this receipt.
        Returns the transaction unchanged if already CONFIRMED or PAID_OUT.
        """
        txn = await self.repo.get_cashback_transaction_by_receipt(receipt_id)
        if txn is None:
            return None

        # Security: ensure the transaction belongs to the requesting user
        if txn.user_id != user_id:
            return None

        # Already confirmed — idempotent
        if txn.status in (CashbackStatus.CONFIRMED, CashbackStatus.PAID_OUT):
            logger.info(f"Cashback already confirmed for receipt {receipt_id}, skipping")
            return txn

        # Confirm the transaction and credit balance + spins atomically
        await self.repo.confirm_transaction(receipt_id)
        await self.repo.upsert_balance_increment(user_id, txn.cashback_amount)
        if txn.spins_awarded > 0:
            await self.repo.add_spins(user_id, txn.spins_awarded)

        txn.status = CashbackStatus.CONFIRMED

        logger.info(
            f"Cashback claimed: receipt={receipt_id}, "
            f"cashback={txn.cashback_amount}, spins={txn.spins_awarded}"
        )
        return txn

    async def get_balance(self, user_id: str) -> CashbackBalance:
        """Return current balance (or create a zero-balance row)."""
        return await self.repo.get_or_create_balance(user_id)

    async def get_transaction_history(
        self, user_id: str, page: int = 1, page_size: int = 20
    ) -> tuple[list[CashbackTransaction], int]:
        """Paginated cashback transaction history."""
        return await self.repo.get_user_cashback_transactions(user_id, page, page_size)

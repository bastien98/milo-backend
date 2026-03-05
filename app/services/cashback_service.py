import logging
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.cashback_repo import CashbackRepository
from app.models.cashback import CashbackTransaction, CashbackBalance

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
        """Award cashback for a completed receipt. Idempotent."""
        # Check idempotency — skip if already awarded
        existing = await self.repo.get_cashback_transaction_by_receipt(receipt_id)
        if existing:
            logger.info(f"Cashback already awarded for receipt {receipt_id}, skipping")
            return existing

        cashback_amount, effective_rate = self.calculate_cashback(receipt_total)

        # Create transaction
        txn = await self.repo.create_cashback_transaction(
            user_id=user_id,
            receipt_id=receipt_id,
            receipt_total=receipt_total,
            cashback_amount=cashback_amount,
            effective_rate=effective_rate,
        )

        # Upsert balance: insert if new user, atomically increment if exists
        await self.repo.upsert_balance_increment(user_id, cashback_amount)

        logger.info(
            f"Cashback awarded: receipt={receipt_id}, "
            f"total={receipt_total}, cashback={cashback_amount}, rate={effective_rate}"
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

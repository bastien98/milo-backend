import logging
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.cashback_repo import CashbackRepository
from app.models.cashback import CashbackTransaction, CashbackBalance

logger = logging.getLogger(__name__)


class CashbackService:
    _SEGMENT_SIZE = Decimal("50")
    _BASE_RATE = Decimal("0.0050")
    _RATE_STEP = Decimal("0.0005")
    _MAX_RATE = Decimal("0.0100")

    # Float aliases for external reference
    SEGMENT_SIZE = 50.0
    BASE_RATE = 0.005
    RATE_STEP = 0.0005
    MAX_RATE = 0.01

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CashbackRepository(db)

    @staticmethod
    def calculate_cashback(total_amount: float) -> tuple[float, float]:
        """Pure function. Returns (cashback_amount, effective_rate).

        Uses Decimal arithmetic internally to avoid floating-point rounding errors.
        """
        if total_amount <= 0:
            return 0.0, 0.0

        remaining = Decimal(str(total_amount))
        cashback = Decimal("0")
        segment = 0

        while remaining > 0:
            rate = min(
                CashbackService._BASE_RATE + segment * CashbackService._RATE_STEP,
                CashbackService._MAX_RATE,
            )
            slice_ = min(remaining, CashbackService._SEGMENT_SIZE)
            cashback += slice_ * rate
            remaining -= slice_
            segment += 1

        cashback = float(cashback.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        effective_rate = round(cashback / total_amount, 6)
        return cashback, effective_rate

    @staticmethod
    def calculate_cashback_segments(total_amount: float) -> list[dict]:
        """Return segment breakdown for preview display."""
        if total_amount <= 0:
            return []

        segments = []
        remaining = Decimal(str(total_amount))
        segment = 0

        while remaining > 0:
            rate = min(
                CashbackService._BASE_RATE + segment * CashbackService._RATE_STEP,
                CashbackService._MAX_RATE,
            )
            slice_ = min(remaining, CashbackService._SEGMENT_SIZE)
            slice_start = segment * CashbackService._SEGMENT_SIZE
            slice_end = slice_start + slice_
            seg_cashback = slice_ * rate
            segments.append(
                {
                    "segment": segment + 1,
                    "slice_start": float(slice_start),
                    "slice_end": float(slice_end),
                    "rate": float(rate),
                    "cashback": float(seg_cashback.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
                }
            )
            remaining -= slice_
            segment += 1

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

        # Ensure balance row exists, then atomically increment
        await self.repo.get_or_create_balance(user_id)
        await self.repo.update_balance_atomic(user_id, cashback_amount)

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

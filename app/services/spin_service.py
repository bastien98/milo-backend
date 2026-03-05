import logging
import random
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.spin_repo import SpinRepository
from app.db.repositories.cashback_repo import CashbackRepository

logger = logging.getLogger(__name__)


@dataclass
class SpinSegment:
    index: int
    label: str
    segment_type: str  # cash, mystery, try_again, double_next, jackpot
    base_value: float
    is_jackpot: bool
    weight: int


# Wheel segments with weights (total = 100)
WHEEL_SEGMENTS = [
    SpinSegment(index=0, label="€0.10",          segment_type="cash",        base_value=0.10, is_jackpot=False, weight=7),
    SpinSegment(index=1, label="Mystery",         segment_type="mystery",     base_value=0.0,  is_jackpot=False, weight=12),
    SpinSegment(index=2, label="€0.50",           segment_type="cash",        base_value=0.50, is_jackpot=False, weight=2),
    SpinSegment(index=3, label="€1",              segment_type="cash",        base_value=1.00, is_jackpot=False, weight=1),
    SpinSegment(index=4, label="€2",              segment_type="cash",        base_value=2.00, is_jackpot=False, weight=1),
    SpinSegment(index=5, label="Double Next",     segment_type="double_next", base_value=0.0,  is_jackpot=False, weight=42),
    SpinSegment(index=6, label="JACKPOT €5",      segment_type="jackpot",     base_value=5.00, is_jackpot=True,  weight=1),
    SpinSegment(index=7, label="Try Again",       segment_type="try_again",   base_value=0.0,  is_jackpot=False, weight=34),
]

# Mystery cash distribution: (value, relative_weight)
MYSTERY_DISTRIBUTION = [
    (0.01, 50),
    (0.02, 25),
    (0.05, 15),
    (0.20, 7),
    (0.50, 2),
    (1.00, 1),
]


def _pick_weighted(segments: list[SpinSegment]) -> SpinSegment:
    """Pick a random segment using weighted probabilities."""
    total_weight = sum(s.weight for s in segments)
    roll = random.randint(0, total_weight - 1)
    for segment in segments:
        roll -= segment.weight
        if roll < 0:
            return segment
    return segments[0]


def _pick_mystery_value() -> float:
    """Pick a random mystery cash value."""
    total = sum(w for _, w in MYSTERY_DISTRIBUTION)
    roll = random.randint(0, total - 1)
    for value, weight in MYSTERY_DISTRIBUTION:
        roll -= weight
        if roll < 0:
            return value
    return 0.01


@dataclass
class SpinOutcome:
    segment: SpinSegment
    cash_value: float
    is_doubled: bool
    mystery_reveal_value: Optional[float]
    grants_free_spin: bool
    grants_double_next: bool


class SpinService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.spin_repo = SpinRepository(db)
        self.cashback_repo = CashbackRepository(db)

    def resolve_spin(self, has_double_next: bool = False) -> SpinOutcome:
        """Determine the spin outcome server-side. Pure logic, no DB."""
        segment = _pick_weighted(WHEEL_SEGMENTS)

        cash_value = 0.0
        mystery_reveal_value = None
        is_doubled = False
        grants_free_spin = False
        grants_double_next = False

        if segment.segment_type == "cash" or segment.segment_type == "jackpot":
            cash_value = segment.base_value
            if has_double_next:
                cash_value *= 2
                is_doubled = True

        elif segment.segment_type == "mystery":
            mystery_reveal_value = _pick_mystery_value()
            cash_value = mystery_reveal_value
            if has_double_next:
                cash_value *= 2
                is_doubled = True

        elif segment.segment_type == "try_again":
            grants_free_spin = True

        elif segment.segment_type == "double_next":
            grants_double_next = True

        return SpinOutcome(
            segment=segment,
            cash_value=round(cash_value, 2),
            is_doubled=is_doubled,
            mystery_reveal_value=mystery_reveal_value,
            grants_free_spin=grants_free_spin,
            grants_double_next=grants_double_next,
        )

    async def execute_spin(
        self, user_id: str, has_double_next: bool = False
    ) -> tuple[SpinOutcome, float, int]:
        """
        Full spin flow:
        1. Resolve outcome
        2. Credit cashback balance if cash won
        3. Record spin transaction
        4. Award free spin if Try Again
        5. Return (outcome, new_balance, spins_remaining)
        """
        outcome = self.resolve_spin(has_double_next)

        # Credit cash to user's cashback balance
        if outcome.cash_value > 0:
            await self.cashback_repo.get_or_create_balance(user_id)
            await self.cashback_repo.update_balance_atomic(user_id, outcome.cash_value)

        # Record the spin transaction
        await self.spin_repo.create_spin_transaction(
            user_id=user_id,
            segment_index=outcome.segment.index,
            segment_label=outcome.segment.label,
            segment_type=outcome.segment.segment_type,
            cash_value=outcome.cash_value,
            is_jackpot=outcome.segment.is_jackpot,
            is_doubled=outcome.is_doubled,
        )

        # Update global budget tracker
        await self.spin_repo.update_budget(outcome.cash_value)

        # Award free spin if Try Again
        spins_delta = 0
        if outcome.grants_free_spin:
            spins_delta = 1  # net zero: used 1, got 1 back

        # Get updated balance
        balance = await self.cashback_repo.get_or_create_balance(user_id)

        return outcome, balance.current_balance, spins_delta

    @staticmethod
    def get_wheel_config() -> list[dict]:
        """Return wheel segment configuration for the frontend."""
        return [
            {
                "index": s.index,
                "label": s.label,
                "segment_type": s.segment_type,
            }
            for s in WHEEL_SEGMENTS
        ]

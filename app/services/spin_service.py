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


# Wheel segments with weights
# Budget: €4,500 for 30,000 spins → €0.15/spin target
# When 2x is active, only €0.05 + Mystery + Retry are eligible (high-value excluded)
WHEEL_SEGMENTS = [
    SpinSegment(index=0, label="€0.10",          segment_type="cash",        base_value=0.10, is_jackpot=False, weight=35),
    SpinSegment(index=1, label="Mystery",         segment_type="mystery",     base_value=0.0,  is_jackpot=False, weight=120),
    SpinSegment(index=2, label="€1",              segment_type="cash",        base_value=1.00, is_jackpot=False, weight=1),
    SpinSegment(index=3, label="Double Next",     segment_type="double_next", base_value=0.0,  is_jackpot=False, weight=107),
    SpinSegment(index=4, label="€0.50",           segment_type="cash",        base_value=0.50, is_jackpot=False, weight=1),
    SpinSegment(index=5, label="Try Again",       segment_type="try_again",   base_value=0.0,  is_jackpot=False, weight=120),
    SpinSegment(index=6, label="€2",              segment_type="cash",        base_value=2.00, is_jackpot=False, weight=1),
    SpinSegment(index=7, label="JACKPOT €5",      segment_type="jackpot",     base_value=5.00, is_jackpot=True,  weight=1),
]

# Max base_value eligible when 2x is active — segments above this are excluded from the pool
DOUBLE_ELIGIBLE_MAX_VALUE = 0.10

# Mystery cash distribution: (value, relative_weight)
# Values deliberately avoid wheel segment amounts (€0.05, €0.50, €1, €2, €5)
# EV ≈ €0.12
MYSTERY_DISTRIBUTION = [
    (0.02, 12),
    (0.04, 15),
    (0.06, 18),
    (0.08, 15),
    (0.15, 16),
    (0.20, 14),
    (0.30, 10),
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
    return 0.02


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

    def resolve_spin(
        self, has_double_next: bool = False, is_respin: bool = False,
        is_last_spin: bool = False, force_segment: Optional[int] = None,
    ) -> SpinOutcome:
        """Determine the spin outcome server-side. Pure logic, no DB."""
        if force_segment is not None and 0 <= force_segment < len(WHEEL_SEGMENTS):
            segment = WHEEL_SEGMENTS[force_segment]
        else:
            excluded_types = set()
            # Prevent consecutive 2x
            if has_double_next:
                excluded_types.add("double_next")
            # Prevent 2x on last spin (no next spin to double)
            if is_last_spin:
                excluded_types.add("double_next")
            # Prevent consecutive retry (Try Again)
            if is_respin:
                excluded_types.add("try_again")

            eligible = [s for s in WHEEL_SEGMENTS if s.segment_type not in excluded_types]

            # When 2x is active, exclude high-value cash/jackpot from pool entirely
            # Only €0.05, Mystery, and Retry can be landed on — guarantees 2x applies
            if has_double_next:
                eligible = [
                    s for s in eligible
                    if s.segment_type not in ("cash", "jackpot")
                    or s.base_value <= DOUBLE_ELIGIBLE_MAX_VALUE
                ]

            segment = _pick_weighted(eligible)

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
            if has_double_next:
                # 2x persists through retry
                grants_double_next = True

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
        self, user_id: str, has_double_next: bool = False, is_respin: bool = False,
        force_segment: Optional[int] = None,
    ) -> tuple[SpinOutcome, float, int]:
        """
        Full spin flow:
        1. Consume a spin from balance (server-side)
        2. Resolve outcome
        3. Credit cashback balance if cash won
        4. Record spin transaction
        5. Award free spin if Try Again
        6. Return (outcome, new_balance, spins_remaining)
        """
        # Consume spin server-side
        await self.cashback_repo.consume_spin(user_id)

        # Check if this was the user's last spin (no spins left after consuming)
        balance_after_consume = await self.cashback_repo.get_or_create_balance(user_id)
        is_last_spin = balance_after_consume.spins_available == 0

        outcome = self.resolve_spin(
            has_double_next, is_respin=is_respin,
            is_last_spin=is_last_spin, force_segment=force_segment,
        )

        # Credit cash to user's cashback balance
        if outcome.cash_value > 0:
            await self.cashback_repo.get_or_create_balance(user_id)
            await self.cashback_repo.upsert_balance_increment(user_id, outcome.cash_value)

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
        if outcome.grants_free_spin:
            await self.cashback_repo.add_spins(user_id, 1)

        # Expire cached ORM objects so we read fresh DB values after all mutations
        await self.db.expire_all()
        balance = await self.cashback_repo.get_or_create_balance(user_id)

        return outcome, balance.current_balance, balance.spins_available

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

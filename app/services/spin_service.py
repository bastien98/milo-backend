"""
Spin service for the Milo Points system.

Two wheel types:
  STANDARD (EV ~100 pts): awarded for Bronze & Silver tier tickets
  PREMIUM  (EV ~200 pts): awarded for Gold tier tickets + Kickstart ticket 1

Segment structure (8 segments per wheel):
  0: Low pts      (high weight)
  1: Mystery      (medium weight) - random value from distribution
  2: High pts     (low weight)
  3: Try Again    (medium weight) - free respin (same spin type)
  4: Medium pts   (medium weight)
  5: Med-high pts (low weight)
  6: Low-med pts  (medium weight)
  7: Jackpot      (ultra-low weight)
"""
import logging
import random
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.spin_repo import SpinRepository
from app.db.repositories.cashback_repo import CashbackRepository
from app.models.enums import SpinType

logger = logging.getLogger(__name__)


@dataclass
class SpinSegment:
    index: int
    label: str
    segment_type: str  # cash, mystery, try_again, jackpot
    base_value: int    # points value (0 for try_again/mystery)
    is_jackpot: bool
    weight: int


# Standard Wheel — EV target: ~100 pts
# Non-try-again pts weights: 50*35 + 200*3 + 100*28 + 150*8 + 75*22 + 1000*1 = 10000
# Non-try-again weight sum: 35+3+28+8+22+1 = 97  -> cash EV = 10000/97 = 103 pts
# Mystery avg ~100 pts. Total EV close to 100.
STANDARD_WHEEL: list[SpinSegment] = [
    SpinSegment(index=0, label="50 pts",   segment_type="cash",      base_value=50,   is_jackpot=False, weight=35),
    SpinSegment(index=1, label="Mystery",  segment_type="mystery",   base_value=0,    is_jackpot=False, weight=20),
    SpinSegment(index=2, label="200 pts",  segment_type="cash",      base_value=200,  is_jackpot=False, weight=3),
    SpinSegment(index=3, label="Try Again",segment_type="try_again", base_value=0,    is_jackpot=False, weight=20),
    SpinSegment(index=4, label="100 pts",  segment_type="cash",      base_value=100,  is_jackpot=False, weight=28),
    SpinSegment(index=5, label="150 pts",  segment_type="cash",      base_value=150,  is_jackpot=False, weight=8),
    SpinSegment(index=6, label="75 pts",   segment_type="cash",      base_value=75,   is_jackpot=False, weight=22),
    SpinSegment(index=7, label="JACKPOT",  segment_type="jackpot",   base_value=1000, is_jackpot=True,  weight=1),
]

# Premium Wheel — EV target: ~200 pts
# Non-try-again pts weights: 100*30 + 400*3 + 200*28 + 300*8 + 150*22 + 2000*1 = 18700
# Non-try-again weight sum: 30+3+28+8+22+1 = 92  -> cash EV = 18700/92 = 203 pts
# Mystery avg ~200 pts. Total EV close to 200.
PREMIUM_WHEEL: list[SpinSegment] = [
    SpinSegment(index=0, label="100 pts",  segment_type="cash",      base_value=100,  is_jackpot=False, weight=30),
    SpinSegment(index=1, label="Mystery",  segment_type="mystery",   base_value=0,    is_jackpot=False, weight=20),
    SpinSegment(index=2, label="400 pts",  segment_type="cash",      base_value=400,  is_jackpot=False, weight=3),
    SpinSegment(index=3, label="Try Again",segment_type="try_again", base_value=0,    is_jackpot=False, weight=20),
    SpinSegment(index=4, label="200 pts",  segment_type="cash",      base_value=200,  is_jackpot=False, weight=28),
    SpinSegment(index=5, label="300 pts",  segment_type="cash",      base_value=300,  is_jackpot=False, weight=8),
    SpinSegment(index=6, label="150 pts",  segment_type="cash",      base_value=150,  is_jackpot=False, weight=22),
    SpinSegment(index=7, label="JACKPOT",  segment_type="jackpot",   base_value=2000, is_jackpot=True,  weight=1),
]

# Mystery distributions: (points_value, weight)
STANDARD_MYSTERY_DISTRIBUTION = [
    (50, 12), (75, 18), (100, 20), (125, 15),
    (150, 12), (175, 10), (200, 8), (250, 5),
]

PREMIUM_MYSTERY_DISTRIBUTION = [
    (100, 12), (150, 18), (200, 20), (250, 15),
    (300, 12), (350, 10), (400, 8), (500, 5),
]


def _pick_weighted(segments: list[SpinSegment]) -> SpinSegment:
    total_weight = sum(s.weight for s in segments)
    roll = random.randint(0, total_weight - 1)
    for segment in segments:
        roll -= segment.weight
        if roll < 0:
            return segment
    return segments[0]


def _pick_mystery_value(distribution: list[tuple[int, int]]) -> int:
    total = sum(w for _, w in distribution)
    roll = random.randint(0, total - 1)
    for value, weight in distribution:
        roll -= weight
        if roll < 0:
            return value
    return distribution[0][0]


@dataclass
class SpinOutcome:
    segment: SpinSegment
    points_value: int
    spin_type: SpinType
    mystery_reveal_value: Optional[int]
    grants_free_spin: bool


class SpinService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.spin_repo = SpinRepository(db)
        self.cashback_repo = CashbackRepository(db)

    def resolve_spin(
        self,
        spin_type: SpinType,
        is_respin: bool = False,
        force_segment: Optional[int] = None,
    ) -> SpinOutcome:
        """Determine the spin outcome server-side. Pure logic, no DB."""
        wheel = STANDARD_WHEEL if spin_type == SpinType.STANDARD else PREMIUM_WHEEL
        mystery_dist = (
            STANDARD_MYSTERY_DISTRIBUTION
            if spin_type == SpinType.STANDARD
            else PREMIUM_MYSTERY_DISTRIBUTION
        )

        if force_segment is not None and 0 <= force_segment < len(wheel):
            segment = wheel[force_segment]
        else:
            eligible = wheel[:]
            if is_respin:
                eligible = [s for s in eligible if s.segment_type != "try_again"]
            segment = _pick_weighted(eligible)

        points_value = 0
        mystery_reveal_value = None
        grants_free_spin = False

        if segment.segment_type in ("cash", "jackpot"):
            points_value = segment.base_value
        elif segment.segment_type == "mystery":
            mystery_reveal_value = _pick_mystery_value(mystery_dist)
            points_value = mystery_reveal_value
        elif segment.segment_type == "try_again":
            grants_free_spin = True

        return SpinOutcome(
            segment=segment,
            points_value=points_value,
            spin_type=spin_type,
            mystery_reveal_value=mystery_reveal_value,
            grants_free_spin=grants_free_spin,
        )

    async def execute_spin(
        self,
        user_id: str,
        spin_type: SpinType,
        is_respin: bool = False,
        force_segment: Optional[int] = None,
    ) -> tuple[SpinOutcome, int, int, int]:
        """
        Full spin flow:
        1. Consume spin from balance
        2. Resolve outcome
        3. Credit points won
        4. Record spin transaction
        5. Award free spin (Try Again)
        Returns: (outcome, points_balance, standard_spins, premium_spins)
        """
        if spin_type == SpinType.STANDARD:
            consumed = await self.cashback_repo.consume_standard_spin(user_id)
        else:
            consumed = await self.cashback_repo.consume_premium_spin(user_id)

        if not consumed:
            raise ValueError(f"No {spin_type.value} spins available for user {user_id}")

        outcome = self.resolve_spin(spin_type, is_respin=is_respin, force_segment=force_segment)

        if outcome.points_value > 0:
            await self.cashback_repo.upsert_points_increment(user_id, outcome.points_value)

        await self.spin_repo.create_spin_transaction(
            user_id=user_id,
            segment_index=outcome.segment.index,
            segment_label=outcome.segment.label,
            segment_type=outcome.segment.segment_type,
            cash_value=round(outcome.points_value / 1000, 4),
            points_value=outcome.points_value,
            is_jackpot=outcome.segment.is_jackpot,
            is_doubled=False,
            spin_type=spin_type,
        )

        await self.spin_repo.update_budget(round(outcome.points_value / 1000, 4))

        if outcome.grants_free_spin:
            if spin_type == SpinType.STANDARD:
                await self.cashback_repo.add_standard_spins(user_id, 1)
            else:
                await self.cashback_repo.add_premium_spins(user_id, 1)

        self.db.expire_all()
        balance = await self.cashback_repo.get_or_create_balance(user_id)

        return outcome, balance.points_balance, balance.standard_spins, balance.premium_spins

    @staticmethod
    def get_wheel_config(spin_type: SpinType = SpinType.STANDARD) -> list[dict]:
        wheel = STANDARD_WHEEL if spin_type == SpinType.STANDARD else PREMIUM_WHEEL
        return [
            {
                "index": s.index,
                "label": s.label,
                "segment_type": s.segment_type,
                "base_value": s.base_value,
            }
            for s in wheel
        ]

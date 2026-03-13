"""
Cashback service for the Milo Points system.

Reward logic per ticket (post-kickstart):

  BRONZE tier: 1 Standard Spin (EV ~100 pts)
  SILVER tier: 1 Standard Spin (EV ~100 pts) + 75 fixed pts
  GOLD tier:   1 Premium Spin  (EV ~200 pts)

  Grote Kar bonus (receipt >= EUR 75, max 6x/month, capped at EUR 300):
    +50 pts per full EUR 75 slice (1-4 slices)
    + SILVER tier extra: +25 pts
    + GOLD tier extra:   +50 pts

Fair-use caps:
  - Day limit:   max 2 tickets/day
  - Week limit:  max 5 tickets/week
  - Month limit: max 15 tickets/month (for rewards); beyond 15 = streak saver (10 pts, no spin)

Kickstart phase (first 3 tickets for new users):
  - Ticket 1: 500 pts + 1 Premium Spin
  - Ticket 2: 500 pts
  - Ticket 3: 500 pts -> kickstart complete
"""
import logging
from dataclasses import dataclass
from math import floor
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.cashback_repo import CashbackRepository
from app.models.cashback import CashbackTransaction, CashbackBalance
from app.models.enums import CashbackStatus, TierLevel, SpinType
from app.services import kickstart_service, tier_service
from app.services.kickstart_service import is_kickstart_active, advance_kickstart
from app.services.tier_service import (
    get_user_tier, count_receipts_this_month,
    count_receipts_today, count_receipts_this_iso_week,
    _current_month_str,
)

logger = logging.getLogger(__name__)

# Limits
DAY_LIMIT = 2
WEEK_LIMIT = 5
MONTH_LIMIT = 15
STREAK_SAVER_POINTS = 10

# Grote Kar constants
GROTE_KAR_THRESHOLD = 75.0
GROTE_KAR_POINTS_PER_SLICE = 50
GROTE_KAR_MAX_SLICES = 4
GROTE_KAR_MONTH_CAP = 6
GROTE_KAR_SILVER_BONUS = 25
GROTE_KAR_GOLD_BONUS = 50

SILVER_FIXED_POINTS = 75


@dataclass
class PointsBreakdown:
    fixed_points: int = 0
    grote_kar_points: int = 0
    kickstart_bonus_points: int = 0
    spin_type: Optional[SpinType] = None
    is_kickstart: bool = False
    is_streak_saver: bool = False

    @property
    def total(self) -> int:
        return self.fixed_points + self.grote_kar_points + self.kickstart_bonus_points


def _compute_grote_kar_points(receipt_total: float, tier: TierLevel) -> int:
    """Calculate Grote Kar bonus points for a qualifying receipt."""
    if receipt_total < GROTE_KAR_THRESHOLD:
        return 0

    slices = min(int(floor(receipt_total / GROTE_KAR_THRESHOLD)), GROTE_KAR_MAX_SLICES)
    base = slices * GROTE_KAR_POINTS_PER_SLICE

    bonus = 0
    if tier == TierLevel.SILVER:
        bonus = GROTE_KAR_SILVER_BONUS
    elif tier == TierLevel.GOLD:
        bonus = GROTE_KAR_GOLD_BONUS

    return base + bonus


def _ensure_grote_kar_month(balance: CashbackBalance, current_month: str) -> None:
    """Reset Grote Kar counter if we've entered a new calendar month."""
    if balance.grote_kar_month != current_month:
        balance.grote_kar_count_this_month = 0
        balance.grote_kar_month = current_month


class CashbackService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CashbackRepository(db)

    async def award_cashback_for_receipt(
        self,
        user_id: str,
        receipt_id: str,
        receipt_total: float,
    ) -> CashbackTransaction:
        """Create a PENDING points transaction for a completed receipt. Idempotent.

        Balance is NOT credited here. The user taps 'Tap to claim' in the app which
        calls claim_cashback() to move the transaction to CONFIRMED and credit points.
        """
        # Idempotency check
        existing = await self.repo.get_cashback_transaction_by_receipt(receipt_id)
        if existing:
            logger.info(f"Transaction already exists for receipt {receipt_id}, skipping")
            return existing

        balance = await self.repo.get_or_create_balance(user_id)
        current_month = _current_month_str()

        # Step 1: Fair-use limit checks (these queries count the current receipt too
        # since it is already COMPLETED when this function is called)
        daily_count = await count_receipts_today(self.db, user_id)
        if daily_count > DAY_LIMIT:
            logger.info(f"Day limit reached for user {user_id} ({daily_count} today)")
            raise ValueError(f"Day limit reached: max {DAY_LIMIT} tickets per day")

        weekly_count = await count_receipts_this_iso_week(self.db, user_id)
        if weekly_count > WEEK_LIMIT:
            logger.info(f"Week limit reached for user {user_id} ({weekly_count} this week)")
            raise ValueError(f"Week limit reached: max {WEEK_LIMIT} tickets per week")

        monthly_count = await count_receipts_this_month(self.db, user_id)

        # Step 2: Update tier for new month if needed
        tier = await get_user_tier(self.db, balance)

        # Step 3: Kickstart path (new users, first 3 tickets)
        if is_kickstart_active(balance):
            reward = advance_kickstart(balance)
            breakdown = PointsBreakdown(
                kickstart_bonus_points=reward.fixed_points,
                spin_type=reward.spin_type,
                is_kickstart=True,
            )
            txn = await self._create_pending_transaction(
                balance=balance,
                receipt_id=receipt_id,
                receipt_total=receipt_total,
                breakdown=breakdown,
            )
            logger.info(
                f"Kickstart reward {reward.ticket_number}/3 for user {user_id}: "
                f"pts={breakdown.total}, spin={reward.spin_type}"
            )
            return txn

        # Step 4: Streak saver (beyond monthly cap of 15)
        # monthly_count already includes this receipt
        if monthly_count > MONTH_LIMIT:
            breakdown = PointsBreakdown(
                fixed_points=STREAK_SAVER_POINTS,
                is_streak_saver=True,
            )
            txn = await self._create_pending_transaction(
                balance=balance,
                receipt_id=receipt_id,
                receipt_total=receipt_total,
                breakdown=breakdown,
            )
            logger.info(f"Streak saver ticket for user {user_id}: +{STREAK_SAVER_POINTS} pts")
            return txn

        # Step 5: Regular reward
        if tier == TierLevel.GOLD:
            spin_type = SpinType.PREMIUM
            fixed_pts = 0
        elif tier == TierLevel.SILVER:
            spin_type = SpinType.STANDARD
            fixed_pts = SILVER_FIXED_POINTS
        else:  # BRONZE
            spin_type = SpinType.STANDARD
            fixed_pts = 0

        # Grote Kar bonus
        _ensure_grote_kar_month(balance, current_month)
        grote_kar_pts = 0
        if (receipt_total >= GROTE_KAR_THRESHOLD
                and balance.grote_kar_count_this_month < GROTE_KAR_MONTH_CAP):
            grote_kar_pts = _compute_grote_kar_points(receipt_total, tier)
            balance.grote_kar_count_this_month += 1

        breakdown = PointsBreakdown(
            fixed_points=fixed_pts,
            grote_kar_points=grote_kar_pts,
            spin_type=spin_type,
        )

        txn = await self._create_pending_transaction(
            balance=balance,
            receipt_id=receipt_id,
            receipt_total=receipt_total,
            breakdown=breakdown,
        )
        logger.info(
            f"Points pending for user {user_id}: tier={tier.value}, "
            f"spin={spin_type.value}, fixed={fixed_pts}, grote_kar={grote_kar_pts}, "
            f"total={breakdown.total}"
        )
        return txn

    async def _create_pending_transaction(
        self,
        balance: CashbackBalance,
        receipt_id: str,
        receipt_total: float,
        breakdown: PointsBreakdown,
    ) -> CashbackTransaction:
        return await self.repo.create_cashback_transaction(
            user_id=balance.user_id,
            receipt_id=receipt_id,
            receipt_total=receipt_total,
            points_total=breakdown.total,
            fixed_points=breakdown.fixed_points,
            grote_kar_points=breakdown.grote_kar_points,
            kickstart_bonus_points=breakdown.kickstart_bonus_points,
            spin_type=breakdown.spin_type,
            is_kickstart=breakdown.is_kickstart,
            is_streak_saver=breakdown.is_streak_saver,
            status=CashbackStatus.PENDING,
        )

    async def claim_cashback(
        self, user_id: str, receipt_id: str
    ) -> Optional[CashbackTransaction]:
        """Confirm a PENDING transaction and credit the user's points wallet. Idempotent."""
        txn = await self.repo.get_cashback_transaction_by_receipt(receipt_id)
        if txn is None:
            return None

        if txn.user_id != user_id:
            return None

        if txn.status in (CashbackStatus.CONFIRMED, CashbackStatus.PAID_OUT):
            logger.info(f"Already confirmed for receipt {receipt_id}, skipping")
            return txn

        await self.repo.confirm_transaction(receipt_id)
        await self.repo.upsert_points_increment(user_id, txn.points_total)

        if txn.spin_type == SpinType.STANDARD:
            await self.repo.add_standard_spins(user_id, 1)
        elif txn.spin_type == SpinType.PREMIUM:
            await self.repo.add_premium_spins(user_id, 1)

        txn.status = CashbackStatus.CONFIRMED

        logger.info(
            f"Points claimed: receipt={receipt_id}, "
            f"points={txn.points_total}, spin={txn.spin_type}"
        )
        return txn

    async def get_balance(self, user_id: str) -> CashbackBalance:
        return await self.repo.get_or_create_balance(user_id)

    async def get_transaction_history(
        self, user_id: str, page: int = 1, page_size: int = 20
    ) -> tuple[list[CashbackTransaction], int]:
        return await self.repo.get_user_cashback_transactions(user_id, page, page_size)

import logging
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cashback import CashbackBalance
from app.models.streak import StreakReward
from app.models.enums import StreakRewardStatus, StreakRewardType

logger = logging.getLogger(__name__)


class StreakService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------ #
    # Reward schedule (pure function)
    # ------------------------------------------------------------------ #

    @staticmethod
    def reward_for_week(week: int) -> dict:
        """Return the reward for a given streak week number.

        Schedule:
          Weeks 1-3:  1 spin/week   | Week 4:  EUR 1
          Weeks 5-7:  2 spins/week  | Week 8:  EUR 1
          Weeks 9-11: 3 spins/week  | Week 12: EUR 1
          Week 13+:   3 spins/week, EUR 1 every 4th week
        """
        if week <= 0:
            return {"type": "spins", "spins": 0, "cash": 0.0}
        if week % 4 == 0:
            return {"type": "cash", "spins": 0, "cash": 1.0}
        # Spins escalate: cycle 0 -> 1 spin, cycle 1 -> 2 spins, cycle 2+ -> 3 spins
        cycle = min((week - 1) // 4, 2)
        return {"type": "spins", "spins": cycle + 1, "cash": 0.0}

    @staticmethod
    def _label_for_reward(reward: dict) -> str:
        if reward["type"] == "cash":
            return "€1"
        spins = reward["spins"]
        return f"{spins} spin{'s' if spins > 1 else ''}"

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def get_streak_status(self, user_id: str) -> dict:
        """Return current streak state for the user."""
        balance = await self._get_or_create_balance(user_id)

        # Check for streak break before returning status
        await self._check_streak_break(balance)

        week_count = balance.streak_week_count

        # Build 4-entry current cycle
        cycle_start = (week_count // 4) * 4 + 1 if week_count % 4 != 0 else max((week_count - 3), 1)
        if week_count == 0:
            cycle_start = 1

        current_cycle = []
        for i in range(4):
            w = cycle_start + i
            reward = self.reward_for_week(w)
            current_cycle.append({
                "week": w,
                "label": self._label_for_reward(reward),
                "reward_type": reward["type"],
                "completed": w <= week_count,
            })

        # Check for claimable reward
        claimable = await self._get_claimable_reward(user_id)

        # Determine at-risk status
        is_at_risk = False
        if balance.streak_last_qualified_at and week_count > 0:
            now = datetime.now(timezone.utc)
            last = balance.streak_last_qualified_at
            # At risk if we're in a new ISO week and haven't qualified yet
            last_iso = last.isocalendar()
            now_iso = now.isocalendar()
            if (now_iso[0], now_iso[1]) != (last_iso[0], last_iso[1]):
                is_at_risk = True

        return {
            "week_count": week_count,
            "current_cycle": current_cycle,
            "claimable_reward": claimable,
            "is_at_risk": is_at_risk,
        }

    async def record_qualifying_receipt(self, user_id: str, receipt_total: float, *, force: bool = False) -> None:
        """Called after a receipt >€50 is processed. Advances streak if not already qualified this week.

        Args:
            force: If True, bypass amount check and ISO week duplicate guard (for test mode).
        """
        if not force and receipt_total <= 50:
            return

        balance = await self._get_or_create_balance(user_id)

        if not force:
            # Check for streak break first
            await self._check_streak_break(balance)

        now = datetime.now(timezone.utc)
        now_iso = now.isocalendar()

        # Check if already qualified this ISO week (skip in force/test mode)
        if not force and balance.streak_last_qualified_at:
            last_iso = balance.streak_last_qualified_at.isocalendar()
            if (now_iso[0], now_iso[1]) == (last_iso[0], last_iso[1]):
                logger.info(f"User {user_id} already qualified this week, skipping streak advance")
                return

        # Advance streak
        balance.streak_week_count += 1
        balance.streak_last_qualified_at = now
        week = balance.streak_week_count

        # Create claimable reward
        reward = self.reward_for_week(week)
        streak_reward = StreakReward(
            id=str(uuid.uuid4()),
            user_id=user_id,
            week_number=week,
            reward_type=StreakRewardType(reward["type"]),
            spins_amount=reward["spins"],
            cash_amount=reward["cash"],
            status=StreakRewardStatus.CLAIMABLE,
        )
        self.db.add(streak_reward)

        logger.info(
            f"Streak advanced for user {user_id}: week {week}, "
            f"reward={reward['type']} (spins={reward['spins']}, cash={reward['cash']})"
        )

    async def claim_reward(self, user_id: str) -> dict:
        """Claim the oldest claimable streak reward. Credits wallet or spins."""
        result = await self.db.execute(
            select(StreakReward)
            .where(
                StreakReward.user_id == user_id,
                StreakReward.status == StreakRewardStatus.CLAIMABLE,
            )
            .order_by(StreakReward.created_at.asc())
            .limit(1)
        )
        reward = result.scalar_one_or_none()

        if reward is None:
            return {
                "success": False,
                "reward_type": "",
                "spins_credited": 0,
                "cash_credited": 0.0,
                "new_balance": 0.0,
                "new_spins_available": 0,
            }

        # Mark as claimed
        reward.status = StreakRewardStatus.CLAIMED
        reward.claimed_at = datetime.now(timezone.utc)

        # Credit the balance
        balance = await self._get_or_create_balance(user_id)

        if reward.reward_type == StreakRewardType.CASH:
            balance.current_balance += reward.cash_amount
            balance.total_earned += reward.cash_amount
        else:
            balance.spins_available += reward.spins_amount

        logger.info(
            f"Streak reward claimed for user {user_id}: week {reward.week_number}, "
            f"type={reward.reward_type.value}, spins={reward.spins_amount}, cash={reward.cash_amount}"
        )

        return {
            "success": True,
            "reward_type": reward.reward_type.value,
            "spins_credited": reward.spins_amount if reward.reward_type == StreakRewardType.SPINS else 0,
            "cash_credited": reward.cash_amount if reward.reward_type == StreakRewardType.CASH else 0.0,
            "new_balance": balance.current_balance,
            "new_spins_available": balance.spins_available,
        }

    # ------------------------------------------------------------------ #
    # Test helpers
    # ------------------------------------------------------------------ #

    async def test_set_week(self, user_id: str, week: int) -> None:
        """Test mode: set streak to a specific week and create a claimable reward."""
        balance = await self._get_or_create_balance(user_id)

        # Clear any existing claimable rewards
        result = await self.db.execute(
            select(StreakReward).where(
                StreakReward.user_id == user_id,
                StreakReward.status == StreakRewardStatus.CLAIMABLE,
            )
        )
        for r in result.scalars().all():
            await self.db.delete(r)

        balance.streak_week_count = week
        balance.streak_last_qualified_at = datetime.now(timezone.utc)

        if week > 0:
            # Create a claimable reward for the target week
            reward = self.reward_for_week(week)
            streak_reward = StreakReward(
                id=str(uuid.uuid4()),
                user_id=user_id,
                week_number=week,
                reward_type=StreakRewardType(reward["type"]),
                spins_amount=reward["spins"],
                cash_amount=reward["cash"],
                status=StreakRewardStatus.CLAIMABLE,
            )
            self.db.add(streak_reward)

        logger.info(f"Test: streak set to week {week} for user {user_id}")

    async def test_reset(self, user_id: str) -> int:
        """Test mode: reset streak to 0 and delete all streak rewards."""
        balance = await self._get_or_create_balance(user_id)
        balance.streak_week_count = 0
        balance.streak_last_qualified_at = None

        result = await self.db.execute(
            select(StreakReward).where(StreakReward.user_id == user_id)
        )
        rewards = result.scalars().all()
        count = len(rewards)
        for r in rewards:
            await self.db.delete(r)

        logger.info(f"Test: streak reset for user {user_id}, deleted {count} rewards")
        return count

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    async def _get_or_create_balance(self, user_id: str) -> CashbackBalance:
        result = await self.db.execute(
            select(CashbackBalance).where(CashbackBalance.user_id == user_id)
        )
        balance = result.scalar_one_or_none()
        if balance is None:
            balance = CashbackBalance(
                id=str(uuid.uuid4()),
                user_id=user_id,
            )
            self.db.add(balance)
            await self.db.flush()
        return balance

    async def _check_streak_break(self, balance: CashbackBalance) -> None:
        """Reset streak if user missed a full ISO week (with 1-day Monday grace)."""
        if balance.streak_week_count == 0 or balance.streak_last_qualified_at is None:
            return

        now = datetime.now(timezone.utc)
        last = balance.streak_last_qualified_at

        last_iso = last.isocalendar()
        now_iso = now.isocalendar()

        # Same week — no break
        if (now_iso[0], now_iso[1]) == (last_iso[0], last_iso[1]):
            return

        # Calculate week gap
        # ISO weeks: year * 52 + week (approximate, handles year boundary)
        last_week_num = last_iso[0] * 53 + last_iso[1]
        now_week_num = now_iso[0] * 53 + now_iso[1]
        week_gap = now_week_num - last_week_num

        if week_gap == 1:
            # One week gap — check Monday grace (today is Monday = weekday 0)
            if now.weekday() == 0:
                # It's Monday, grace period still active
                return
            # Past Monday — if gap is exactly 1 week, streak is at risk but not broken yet
            # The streak only breaks when we're 2+ weeks behind
            return

        if week_gap >= 2:
            # Missed a full week — streak is broken
            logger.info(
                f"Streak broken for user {balance.user_id}: "
                f"week_gap={week_gap}, resetting from {balance.streak_week_count}"
            )
            balance.streak_week_count = 0
            balance.streak_last_qualified_at = None

            # Also expire any unclaimed rewards
            result = await self.db.execute(
                select(StreakReward).where(
                    StreakReward.user_id == balance.user_id,
                    StreakReward.status == StreakRewardStatus.CLAIMABLE,
                )
            )
            for reward in result.scalars().all():
                reward.status = StreakRewardStatus.CLAIMED
                reward.claimed_at = datetime.now(timezone.utc)

    async def _get_claimable_reward(self, user_id: str) -> dict | None:
        result = await self.db.execute(
            select(StreakReward)
            .where(
                StreakReward.user_id == user_id,
                StreakReward.status == StreakRewardStatus.CLAIMABLE,
            )
            .order_by(StreakReward.created_at.asc())
            .limit(1)
        )
        reward = result.scalar_one_or_none()
        if reward is None:
            return None

        return {
            "reward_id": reward.id,
            "week_number": reward.week_number,
            "reward_type": reward.reward_type.value,
            "spins_amount": reward.spins_amount,
            "cash_amount": reward.cash_amount,
        }

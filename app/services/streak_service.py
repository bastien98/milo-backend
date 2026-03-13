"""
Streak service for the Milo Points system.

Two-level streak model based on calendar weeks:

Level 1 (first month cycle, 4 weeks):
  Week 1: nothing
  Week 2: +1 Standard Spin
  Week 3: +150 fixed pts
  Week 4: +1 Premium Spin + 50 fixed pts  (climax)

Level 2 (continuous streak, month 2+):
  Week 1: +150 pts
  Week 2: +1 Standard Spin + 100 pts
  Week 3: +1 Standard Spin + 150 pts
  Week 4: +1 Premium Spin + 200 pts  (climax)

After completing Level 1 week 4 and scanning the next week without a break,
the streak advances to Level 2. Completing Level 2 week 4 restarts the Level 2 cycle.

Break rule: miss 2+ ISO weeks -> streak resets to Level 1 week 0.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cashback import CashbackBalance
from app.models.streak import StreakReward
from app.models.enums import StreakRewardStatus, StreakRewardType, SpinType

logger = logging.getLogger(__name__)

LEVEL_1 = 1
LEVEL_2 = 2


def reward_for_week(week_in_cycle: int, streak_level: int) -> dict:
    """Return the reward for the given cycle position (1-4) at the given streak level.

    Returns dict: {type, spins, spin_type, points}
    """
    if week_in_cycle <= 0:
        return {"type": "none", "spins": 0, "spin_type": None, "points": 0}

    cycle_week = ((week_in_cycle - 1) % 4) + 1  # normalize to 1-4

    if streak_level == LEVEL_1:
        schedule = {
            1: {"type": "none",   "spins": 0, "spin_type": None,              "points": 0},
            2: {"type": "spins",  "spins": 1, "spin_type": SpinType.STANDARD, "points": 0},
            3: {"type": "points", "spins": 0, "spin_type": None,              "points": 150},
            4: {"type": "mixed",  "spins": 1, "spin_type": SpinType.PREMIUM,  "points": 50},
        }
    else:  # LEVEL_2
        schedule = {
            1: {"type": "points", "spins": 0, "spin_type": None,              "points": 150},
            2: {"type": "mixed",  "spins": 1, "spin_type": SpinType.STANDARD, "points": 100},
            3: {"type": "mixed",  "spins": 1, "spin_type": SpinType.STANDARD, "points": 150},
            4: {"type": "mixed",  "spins": 1, "spin_type": SpinType.PREMIUM,  "points": 200},
        }

    return schedule[cycle_week]


def _label_for_reward(reward: dict) -> str:
    if reward["type"] == "none":
        return "Geen beloning"
    parts = []
    if reward["spins"]:
        spin_name = "Premium Spin" if reward["spin_type"] == SpinType.PREMIUM else "Standaard Spin"
        parts.append(f"1 {spin_name}")
    if reward["points"]:
        parts.append(f"{reward['points']} pts")
    return " + ".join(parts) if parts else "Geen beloning"


class StreakService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_streak_status(self, user_id: str) -> dict:
        balance = await self._get_or_create_balance(user_id)
        await self._check_streak_break(balance)

        week_count = balance.streak_week_count
        streak_level = balance.streak_level
        cycle_week = ((week_count - 1) % 4) + 1 if week_count > 0 else 0

        # Build 4-entry current cycle
        cycle_start_abs = week_count - (cycle_week - 1) if week_count > 0 else 1
        current_cycle = []
        for i in range(4):
            abs_week = cycle_start_abs + i
            cycle_pos = i + 1
            reward = reward_for_week(cycle_pos, streak_level)
            current_cycle.append({
                "week": abs_week,
                "cycle_position": cycle_pos,
                "label": _label_for_reward(reward),
                "reward_type": reward["type"],
                "completed": abs_week <= week_count,
            })

        claimable = await self._get_claimable_reward(user_id)

        is_at_risk = False
        if balance.streak_last_qualified_at and week_count > 0:
            now = datetime.now(timezone.utc)
            last_iso = balance.streak_last_qualified_at.isocalendar()
            now_iso = now.isocalendar()
            if (now_iso[0], now_iso[1]) != (last_iso[0], last_iso[1]):
                is_at_risk = True

        return {
            "week_count": week_count,
            "streak_level": streak_level,
            "current_cycle": current_cycle,
            "claimable_reward": claimable,
            "is_at_risk": is_at_risk,
        }

    async def record_qualifying_receipt(
        self, user_id: str, receipt_total: float = 0.0, *, force: bool = False
    ) -> None:
        """Called after a receipt is processed. All receipts qualify for streak (no minimum)."""
        balance = await self._get_or_create_balance(user_id)

        if not force:
            await self._check_streak_break(balance)

        now = datetime.now(timezone.utc)
        now_iso = now.isocalendar()

        if not force and balance.streak_last_qualified_at:
            last_iso = balance.streak_last_qualified_at.isocalendar()
            if (now_iso[0], now_iso[1]) == (last_iso[0], last_iso[1]):
                logger.info(f"User {user_id} already qualified this week, skipping streak advance")
                return

        balance.streak_week_count += 1
        balance.streak_last_qualified_at = now
        week_count = balance.streak_week_count

        cycle_week = ((week_count - 1) % 4) + 1  # 1-4
        is_completing_level1_cycle = (balance.streak_level == LEVEL_1 and cycle_week == 4)

        reward = reward_for_week(cycle_week, balance.streak_level)

        if reward["type"] != "none":
            reward_type = StreakRewardType.SPINS if reward["spins"] else StreakRewardType.POINTS
            streak_reward = StreakReward(
                id=str(uuid.uuid4()),
                user_id=user_id,
                week_number=week_count,
                reward_type=reward_type,
                spins_amount=reward["spins"],
                cash_amount=0.0,
                points_amount=reward["points"],
                spin_type=reward["spin_type"],
                streak_level=balance.streak_level,
                status=StreakRewardStatus.CLAIMABLE,
            )
            self.db.add(streak_reward)

        if is_completing_level1_cycle:
            balance.streak_level = LEVEL_2
            logger.info(f"User {user_id} advanced to Level 2 streak!")

        logger.info(
            f"Streak advanced: user={user_id}, week={week_count}, "
            f"level={balance.streak_level}, cycle_week={cycle_week}"
        )

    async def claim_reward(self, user_id: str) -> dict:
        """Claim the oldest claimable streak reward."""
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
                "spin_type": None,
                "points_credited": 0,
                "new_points_balance": 0,
                "new_standard_spins": 0,
                "new_premium_spins": 0,
            }

        reward.status = StreakRewardStatus.CLAIMED
        reward.claimed_at = datetime.now(timezone.utc)

        balance = await self._get_or_create_balance(user_id)

        if reward.spins_amount > 0 and reward.spin_type:
            if reward.spin_type == SpinType.STANDARD:
                balance.standard_spins += reward.spins_amount
            else:
                balance.premium_spins += reward.spins_amount

        if reward.points_amount > 0:
            balance.points_balance += reward.points_amount
            balance.total_points_earned += reward.points_amount

        logger.info(
            f"Streak reward claimed: user={user_id}, week={reward.week_number}, "
            f"level={reward.streak_level}, spins={reward.spins_amount}, pts={reward.points_amount}"
        )

        return {
            "success": True,
            "reward_type": reward.reward_type.value,
            "spins_credited": reward.spins_amount,
            "spin_type": reward.spin_type.value if reward.spin_type else None,
            "points_credited": reward.points_amount,
            "new_points_balance": balance.points_balance,
            "new_standard_spins": balance.standard_spins,
            "new_premium_spins": balance.premium_spins,
        }

    # ── Test helpers ────────────────────────────────────────────────────────

    async def test_set_week(self, user_id: str, week: int, streak_level: int = 1) -> None:
        balance = await self._get_or_create_balance(user_id)

        result = await self.db.execute(
            select(StreakReward).where(
                StreakReward.user_id == user_id,
                StreakReward.status == StreakRewardStatus.CLAIMABLE,
            )
        )
        for r in result.scalars().all():
            await self.db.delete(r)

        balance.streak_week_count = week
        balance.streak_level = streak_level
        balance.streak_last_qualified_at = datetime.now(timezone.utc) if week > 0 else None

        if week > 0:
            cycle_week = ((week - 1) % 4) + 1
            reward = reward_for_week(cycle_week, streak_level)
            if reward["type"] != "none":
                reward_type = StreakRewardType.SPINS if reward["spins"] else StreakRewardType.POINTS
                streak_reward = StreakReward(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    week_number=week,
                    reward_type=reward_type,
                    spins_amount=reward["spins"],
                    cash_amount=0.0,
                    points_amount=reward["points"],
                    spin_type=reward["spin_type"],
                    streak_level=streak_level,
                    status=StreakRewardStatus.CLAIMABLE,
                )
                self.db.add(streak_reward)

        logger.info(f"Test: streak set to week={week}, level={streak_level} for user {user_id}")

    async def test_reset(self, user_id: str) -> int:
        balance = await self._get_or_create_balance(user_id)
        balance.streak_week_count = 0
        balance.streak_level = LEVEL_1
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

    # ── Private helpers ─────────────────────────────────────────────────────

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
        """Reset streak if user missed 2+ ISO weeks."""
        if balance.streak_week_count == 0 or balance.streak_last_qualified_at is None:
            return

        now = datetime.now(timezone.utc)
        last = balance.streak_last_qualified_at

        last_iso = last.isocalendar()
        now_iso = now.isocalendar()

        if (now_iso[0], now_iso[1]) == (last_iso[0], last_iso[1]):
            return

        last_week_num = last_iso[0] * 53 + last_iso[1]
        now_week_num = now_iso[0] * 53 + now_iso[1]
        week_gap = now_week_num - last_week_num

        if week_gap == 1:
            # One week gap — streak is at risk but not broken
            return

        if week_gap >= 2:
            logger.info(
                f"Streak broken for user {balance.user_id}: "
                f"week_gap={week_gap}, resetting from week={balance.streak_week_count}, "
                f"level={balance.streak_level}"
            )
            balance.streak_week_count = 0
            balance.streak_level = LEVEL_1
            balance.streak_last_qualified_at = None

            result = await self.db.execute(
                select(StreakReward).where(
                    StreakReward.user_id == balance.user_id,
                    StreakReward.status == StreakRewardStatus.CLAIMABLE,
                )
            )
            for r in result.scalars().all():
                r.status = StreakRewardStatus.CLAIMED
                r.claimed_at = datetime.now(timezone.utc)

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
            "spin_type": reward.spin_type.value if reward.spin_type else None,
            "points_amount": reward.points_amount,
            "streak_level": reward.streak_level,
        }

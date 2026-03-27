"""Referral service: code generation, application, and reward granting."""

import logging
import random
import string
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brand_cashback import UserBrandCashbackClaim
from app.models.referral import Referral
from app.models.user import User
from app.models.user_profile import UserProfile
from app.models.enums import ReferralStatus
from app.db.repositories.cashback_repo import CashbackRepository

logger = logging.getLogger(__name__)

REWARD_EUROS = 1.0
REWARD_SPINS = 0


class ReferralService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Code generation
    # ------------------------------------------------------------------

    async def _generate_code_from_nickname(self, firebase_uid: str) -> str:
        """Build a 6-char code from the user's nickname, with random padding."""
        result = await self.db.execute(
            select(UserProfile.nickname).where(UserProfile.user_id == firebase_uid)
        )
        nickname = result.scalar_one_or_none()

        if nickname:
            base = "".join(c for c in nickname.upper() if c.isalnum())[:6]
        else:
            base = ""

        # Pad to 6 chars with random alphanumeric
        while len(base) < 6:
            base += random.choice(string.ascii_uppercase + string.digits)

        return base[:6]

    async def _is_code_taken(self, code: str) -> bool:
        result = await self.db.execute(
            select(func.count()).select_from(UserProfile).where(
                UserProfile.referral_code == code
            )
        )
        return (result.scalar() or 0) > 0

    async def generate_referral_code(self, firebase_uid: str) -> str:
        """Generate (or return existing) referral code for a user."""
        # Check if code already exists
        result = await self.db.execute(
            select(UserProfile.referral_code).where(
                UserProfile.user_id == firebase_uid
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        # Generate new code with collision retry
        code = await self._generate_code_from_nickname(firebase_uid)
        attempts = 0
        while await self._is_code_taken(code) and attempts < 10:
            # Replace last 2 chars with random to resolve collision
            code = code[:4] + random.choice(string.ascii_uppercase + string.digits) + random.choice(string.ascii_uppercase + string.digits)
            attempts += 1

        if await self._is_code_taken(code):
            # Fallback to fully random
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

        # Save to profile
        await self.db.execute(
            select(UserProfile).where(UserProfile.user_id == firebase_uid)
        )
        from sqlalchemy import update
        await self.db.execute(
            update(UserProfile)
            .where(UserProfile.user_id == firebase_uid)
            .values(referral_code=code)
        )
        await self.db.flush()
        return code

    # ------------------------------------------------------------------
    # Referral info
    # ------------------------------------------------------------------

    async def get_referral_info(self, user: User) -> dict:
        """Get user's referral code, stats, and unclaimed reward info."""
        code = await self.generate_referral_code(user.firebase_uid)

        # Count referrals made by this user
        result = await self.db.execute(
            select(
                func.count().label("total"),
                func.count().filter(Referral.status == ReferralStatus.COMPLETED).label("completed"),
                func.count().filter(Referral.status == ReferralStatus.PENDING).label("pending"),
            ).where(Referral.referrer_id == user.id)
        )
        row = result.one()

        # Check for unclaimed referral reward (user could be referrer or referee)
        unclaimed = await self._find_unclaimed_referral(user.id)

        info = {
            "referral_code": code,
            "total_referrals": row.total,
            "completed_referrals": row.completed,
            "pending_referrals": row.pending,
            "total_earned": row.completed * REWARD_EUROS,
            "has_unclaimed_reward": False,
            "unclaimed_reward_euros": 0.0,
            "unclaimed_reward_spins": 0,
            "unclaimed_referral_id": None,
            "unclaimed_referral_role": None,
        }

        if unclaimed:
            referral, role = unclaimed
            info["has_unclaimed_reward"] = True
            info["unclaimed_reward_euros"] = REWARD_EUROS
            info["unclaimed_reward_spins"] = REWARD_SPINS
            info["unclaimed_referral_id"] = referral.id
            info["unclaimed_referral_role"] = role

        return info

    async def _find_unclaimed_referral(self, user_id: str):
        """Find the oldest unclaimed referral reward for a user."""
        result = await self.db.execute(
            select(Referral).where(
                Referral.status == ReferralStatus.COMPLETED,
                or_(
                    and_(Referral.referrer_id == user_id, Referral.referrer_reward_claimed == False),
                    and_(Referral.referee_id == user_id, Referral.referee_reward_claimed == False),
                ),
            ).order_by(Referral.completed_at.asc()).limit(1)
        )
        referral = result.scalar_one_or_none()
        if not referral:
            return None

        role = "referrer" if referral.referrer_id == user_id else "referee"
        return referral, role

    # ------------------------------------------------------------------
    # Apply referral code (referee side)
    # ------------------------------------------------------------------

    async def apply_referral_code(self, referee_user: User, code: str) -> dict:
        """Referee applies a referral code. Creates a PENDING referral."""
        code = code.strip().upper()

        # Find the referrer's profile by code
        result = await self.db.execute(
            select(UserProfile).where(UserProfile.referral_code == code)
        )
        referrer_profile = result.scalar_one_or_none()
        if not referrer_profile:
            return {"success": False, "message": "Invalid referral code.", "referrer_name": None}

        # Prevent self-referral
        if referrer_profile.user_id == referee_user.firebase_uid:
            return {"success": False, "message": "You cannot use your own referral code.", "referrer_name": None}

        # Check referee hasn't already been referred
        result = await self.db.execute(
            select(func.count()).select_from(Referral).where(
                Referral.referee_id == referee_user.id
            )
        )
        if (result.scalar() or 0) > 0:
            return {"success": False, "message": "You have already used a referral code.", "referrer_name": None}

        # Look up referrer's users.id from firebase_uid
        result = await self.db.execute(
            select(User).where(User.firebase_uid == referrer_profile.user_id)
        )
        referrer_user = result.scalar_one_or_none()
        if not referrer_user:
            return {"success": False, "message": "Invalid referral code.", "referrer_name": None}

        # Create PENDING referral
        referral = Referral(
            id=str(uuid.uuid4()),
            referrer_id=referrer_user.id,
            referee_id=referee_user.id,
            referral_code=code,
            status=ReferralStatus.PENDING,
        )
        self.db.add(referral)

        # Store referred_by_code on referee's profile
        from sqlalchemy import update
        await self.db.execute(
            update(UserProfile)
            .where(UserProfile.user_id == referee_user.firebase_uid)
            .values(referred_by_code=code)
        )
        await self.db.flush()

        referrer_name = referrer_profile.nickname or referrer_profile.first_name
        return {
            "success": True,
            "message": "Referral code applied! You'll both earn rewards once you claim a cashback deal and earn it by uploading a receipt.",
            "referrer_name": referrer_name,
        }

    # ------------------------------------------------------------------
    # Complete referral on brand cashback earned
    # ------------------------------------------------------------------

    async def complete_referral_on_brand_cashback_earned(self, user_id: str) -> bool:
        """Called after a referee earns brand cashback (uploaded a receipt matching a claimed deal).

        user_id is users.id (not firebase_uid).
        Marks referral as COMPLETED but does NOT credit rewards.
        Rewards are claimed later via claim_referral_reward().
        Returns True if a referral was completed.
        """
        # Check if a PENDING referral exists for this user as referee
        result = await self.db.execute(
            select(Referral).where(
                Referral.referee_id == user_id,
                Referral.status == ReferralStatus.PENDING,
            )
        )
        referral = result.scalar_one_or_none()
        if not referral:
            return False

        # Verify the referee has at least one earned brand cashback claim
        result = await self.db.execute(
            select(func.count()).select_from(UserBrandCashbackClaim).where(
                UserBrandCashbackClaim.user_id == user_id,
                UserBrandCashbackClaim.status == "earned",
            )
        )
        earned_count = result.scalar() or 0
        if earned_count < 1:
            return False

        # Mark referral as completed (rewards ready to claim, not auto-credited)
        referral.status = ReferralStatus.COMPLETED
        referral.completed_at = datetime.now(timezone.utc)
        await self.db.flush()

        logger.info(
            f"Referral completed via brand cashback earned: referee={user_id}, "
            f"referrer={referral.referrer_id}, code={referral.referral_code}"
        )
        return True

    # ------------------------------------------------------------------
    # Claim referral reward
    # ------------------------------------------------------------------

    async def claim_referral_reward(self, user: User) -> dict:
        """Claim an unclaimed referral reward for the user.

        Finds the oldest unclaimed reward, credits EUR + spins, marks as claimed.
        """
        unclaimed = await self._find_unclaimed_referral(user.id)
        if not unclaimed:
            return {
                "success": False,
                "message": "No unclaimed referral reward found.",
                "euros_credited": 0.0,
                "spins_credited": 0,
                "new_balance": 0.0,
            }

        referral, role = unclaimed

        # Credit reward to this user
        cashback_repo = CashbackRepository(self.db)
        await cashback_repo.upsert_balance_increment(user.id, REWARD_EUROS)

        # Mark this side as claimed
        if role == "referrer":
            referral.referrer_reward_claimed = True
        else:
            referral.referee_reward_claimed = True

        # If both sides claimed, mark rewards_granted
        if referral.referrer_reward_claimed and referral.referee_reward_claimed:
            referral.rewards_granted = True

        await self.db.flush()

        # Get updated balance
        balance = await cashback_repo.get_or_create_balance(user.id)

        logger.info(
            f"Referral reward claimed: user={user.id}, role={role}, "
            f"referral={referral.id}, EUR {REWARD_EUROS}"
        )

        return {
            "success": True,
            "message": f"You earned EUR {REWARD_EUROS:.2f}!",
            "euros_credited": REWARD_EUROS,
            "spins_credited": 0,
            "new_balance": balance.current_balance,
        }

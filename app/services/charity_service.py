import logging
import math
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.repositories.cashback_repo import CashbackRepository
from app.models.charity_donation import CharityDonation
from app.models.enums import CharityDonationStatus
from app.models.user import User
from app.services.fraud_check_service import FraudCheckService

logger = logging.getLogger(__name__)

POINTS_PER_EURO = 1000
VALID_DONATION_AMOUNTS = [5.0, 10.0, 15.0, 20.0]

BELGIAN_CHARITIES = [
    {
        "id": "rode_kruis",
        "name": "Rode Kruis-Vlaanderen",
        "description": "Belgian Red Cross – emergency aid & blood services",
        "icon": "heart.fill",
        "color": "red",
    },
    {
        "id": "msf_belgium",
        "name": "Artsen Zonder Grenzen",
        "description": "Medical aid in crisis zones worldwide",
        "icon": "stethoscope",
        "color": "orange",
    },
    {
        "id": "unicef_belgium",
        "name": "UNICEF België",
        "description": "Children's rights and survival worldwide",
        "icon": "figure.child",
        "color": "blue",
    },
    {
        "id": "plan_belgium",
        "name": "Plan International",
        "description": "Youth empowerment in 75+ countries",
        "icon": "globe.europe.africa.fill",
        "color": "green",
    },
    {
        "id": "oxfam_belgium",
        "name": "Oxfam-Solidarité",
        "description": "Fighting inequality and extreme poverty",
        "icon": "hands.and.sparkles.fill",
        "color": "purple",
    },
    {
        "id": "handicap_intl",
        "name": "Handicap International",
        "description": "Aid and inclusion for people with disabilities",
        "icon": "figure.roll",
        "color": "yellow",
    },
]

_CHARITY_MAP = {c["id"]: c for c in BELGIAN_CHARITIES}


class CharityService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.cashback_repo = CashbackRepository(db)
        self.fraud_service = FraudCheckService(db)

    async def get_charities_with_totals(self, user_id: str) -> tuple[list[dict], float]:
        """Return charity list with community totals and user totals.
        Returns (charities_with_totals, user_balance_euros).
        """
        # Community totals per charity (transferred + pending both count for display)
        community_result = await self.db.execute(
            select(
                CharityDonation.charity_id,
                func.sum(CharityDonation.amount).label("total"),
            ).group_by(CharityDonation.charity_id)
        )
        community_totals = {row.charity_id: row.total for row in community_result.all()}

        # User totals per charity
        user_result = await self.db.execute(
            select(
                CharityDonation.charity_id,
                func.sum(CharityDonation.amount).label("total"),
            )
            .where(CharityDonation.user_id == user_id)
            .group_by(CharityDonation.charity_id)
        )
        user_totals = {row.charity_id: row.total for row in user_result.all()}

        # Current user balance
        balance = await self.cashback_repo.get_or_create_balance(user_id)
        user_balance = round(balance.points_balance / POINTS_PER_EURO, 2)

        charities = []
        for c in BELGIAN_CHARITIES:
            charities.append({
                **c,
                "community_total": round(community_totals.get(c["id"], 0.0), 2),
                "user_total": round(user_totals.get(c["id"], 0.0), 2),
            })

        return charities, user_balance

    async def create_donation(self, user: User, charity_id: str, amount: float) -> dict:
        """Create a charity donation, deducting from the user's wallet."""
        # Validate charity
        if charity_id not in _CHARITY_MAP:
            raise ValueError(f"Unknown charity: {charity_id}")
        charity = _CHARITY_MAP[charity_id]

        # Validate amount
        if amount not in VALID_DONATION_AMOUNTS:
            raise ValueError(f"Invalid amount. Must be one of: {VALID_DONATION_AMOUNTS}")

        # Check balance
        balance = await self.cashback_repo.get_or_create_balance(user.id)
        current_balance = round(balance.points_balance / POINTS_PER_EURO, 2)
        if amount > current_balance:
            raise ValueError("Insufficient balance")

        # Run fraud checks (same as cash withdrawal)
        fraud_passed, fraud_details = await self.fraud_service.run_checks(user.id)

        # Atomically deduct balance
        points_to_deduct = round(amount * POINTS_PER_EURO)
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from app.models.cashback import CashbackBalance
        result = await self.db.execute(
            update(CashbackBalance)
            .where(
                CashbackBalance.user_id == user.id,
                CashbackBalance.points_balance >= points_to_deduct,
            )
            .values(points_balance=CashbackBalance.points_balance - points_to_deduct)
        )
        await self.db.flush()
        if result.rowcount == 0:
            raise ValueError("Insufficient balance (concurrent modification)")

        # Create donation record
        donation = CharityDonation(
            user_id=user.id,
            charity_id=charity_id,
            charity_name=charity["name"],
            amount=amount,
            status=CharityDonationStatus.PENDING,
            fraud_check_passed=fraud_passed,
            fraud_check_details=fraud_details,
        )
        self.db.add(donation)
        await self.db.flush()

        # Get updated balance
        new_balance_row = await self.cashback_repo.get_or_create_balance(user.id)
        new_balance = round(new_balance_row.points_balance / POINTS_PER_EURO, 2)

        return {
            "id": donation.id,
            "charity_id": charity_id,
            "charity_name": charity["name"],
            "amount": amount,
            "status": donation.status,
            "fraud_check_passed": fraud_passed,
            "new_balance": new_balance,
        }

    async def get_user_donations(self, user_id: str) -> tuple[list[CharityDonation], float]:
        """Return user donations and total donated."""
        result = await self.db.execute(
            select(CharityDonation)
            .where(CharityDonation.user_id == user_id)
            .order_by(CharityDonation.created_at.desc())
        )
        donations = list(result.scalars().all())
        total = sum(d.amount for d in donations)
        return donations, total

    async def get_all_pending(self) -> list[CharityDonation]:
        """Admin: all pending donations with user info."""
        result = await self.db.execute(
            select(CharityDonation)
            .options(selectinload(CharityDonation.user))
            .where(CharityDonation.status == CharityDonationStatus.PENDING)
            .order_by(CharityDonation.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_all_donations(self) -> list[CharityDonation]:
        """Admin: all donations with user info."""
        result = await self.db.execute(
            select(CharityDonation)
            .options(selectinload(CharityDonation.user))
            .order_by(CharityDonation.created_at.desc())
        )
        return list(result.scalars().all())

    async def mark_transferred(self, donation_id: str) -> CharityDonation:
        """Admin: mark a donation as transferred."""
        result = await self.db.execute(
            select(CharityDonation).where(CharityDonation.id == donation_id)
        )
        donation = result.scalar_one_or_none()
        if not donation:
            raise ValueError("Donation not found")
        if donation.status == CharityDonationStatus.TRANSFERRED:
            raise ValueError("Donation already marked as transferred")

        donation.status = CharityDonationStatus.TRANSFERRED
        donation.transferred_at = datetime.now(timezone.utc)
        await self.db.flush()
        return donation

    async def mark_charity_transferred(self, charity_id: str) -> int:
        """Admin: mark ALL pending donations for a charity as transferred. Returns count."""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            update(CharityDonation)
            .where(
                CharityDonation.charity_id == charity_id,
                CharityDonation.status == CharityDonationStatus.PENDING,
            )
            .values(status=CharityDonationStatus.TRANSFERRED, transferred_at=now)
        )
        await self.db.flush()
        return result.rowcount

    async def get_admin_summary(self) -> list[dict]:
        """Admin: summary of pending and transferred amounts per charity."""
        result = await self.db.execute(
            select(
                CharityDonation.charity_id,
                CharityDonation.charity_name,
                CharityDonation.status,
                func.sum(CharityDonation.amount).label("total"),
                func.count().label("count"),
            )
            .group_by(CharityDonation.charity_id, CharityDonation.charity_name, CharityDonation.status)
        )
        rows = result.all()

        # Build per-charity summary
        summary: dict[str, dict] = {}
        for row in rows:
            if row.charity_id not in summary:
                summary[row.charity_id] = {
                    "charity_id": row.charity_id,
                    "charity_name": row.charity_name,
                    "pending_total": 0.0,
                    "pending_count": 0,
                    "transferred_total": 0.0,
                    "transferred_count": 0,
                }
            if row.status == CharityDonationStatus.PENDING:
                summary[row.charity_id]["pending_total"] = round(row.total, 2)
                summary[row.charity_id]["pending_count"] = row.count
            elif row.status == CharityDonationStatus.TRANSFERRED:
                summary[row.charity_id]["transferred_total"] = round(row.total, 2)
                summary[row.charity_id]["transferred_count"] = row.count

        return list(summary.values())

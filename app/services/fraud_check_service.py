import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cashback import CashbackTransaction, CashbackBalance
from app.models.enums import CashbackStatus, WithdrawalStatus
from app.models.receipt import Receipt
from app.models.user import User
from app.models.withdrawal import WithdrawalRequest

logger = logging.getLogger(__name__)

# Recognized Belgian grocery stores (case-insensitive matching)
BELGIAN_GROCERY_STORES = {
    "colruyt", "delhaize", "lidl", "aldi", "carrefour", "albert heijn",
    "intermarche", "intermarché", "match", "okay", "proxy delhaize",
    "spar", "cora", "makro", "bio-planet", "bioplanet",
    "okay compact", "colruyt group", "ah", "jumbo", "plus",
}


class FraudCheckService:
    """Automated fraud checks for withdrawal requests.

    Checks Belgian grocery spending behavior. All checks must pass
    for auto-approval; otherwise flags for manual review.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def run_checks(self, user_id: str) -> tuple[bool, dict]:
        """Run all fraud checks. Returns (all_passed, details_dict)."""
        details = {}

        # 1. Account age >= 14 days
        account_age_ok, account_age_info = await self._check_account_age(user_id)
        details["account_age"] = account_age_info

        # 2. At least 5 verified/confirmed receipts
        receipt_count_ok, receipt_count_info = await self._check_receipt_count(user_id)
        details["receipt_count"] = receipt_count_info

        # 3. Balance accumulated over 7+ days
        accumulation_ok, accumulation_info = await self._check_accumulation_period(user_id)
        details["accumulation_period"] = accumulation_info

        # 4. Receipts from recognized Belgian grocery stores
        stores_ok, stores_info = await self._check_grocery_stores(user_id)
        details["grocery_stores"] = stores_info

        # 5. Receipt totals in normal range (EUR 5-300, avg > EUR 15)
        totals_ok, totals_info = await self._check_receipt_totals(user_id)
        details["receipt_totals"] = totals_info

        # 6. No previous rejected withdrawal
        no_rejection_ok, rejection_info = await self._check_no_previous_rejection(user_id)
        details["no_previous_rejection"] = rejection_info

        # 7. No duplicate receipt patterns
        no_duplicates_ok, duplicates_info = await self._check_no_duplicates(user_id)
        details["no_duplicate_patterns"] = duplicates_info

        all_passed = all([
            account_age_ok, receipt_count_ok, accumulation_ok,
            stores_ok, totals_ok, no_rejection_ok, no_duplicates_ok,
        ])
        details["all_passed"] = all_passed

        logger.info(f"Fraud checks for user {user_id}: passed={all_passed}, details={details}")
        return all_passed, details

    async def _check_account_age(self, user_id: str) -> tuple[bool, dict]:
        result = await self.db.execute(
            select(User.created_at).where(User.id == user_id)
        )
        created_at = result.scalar_one_or_none()
        if created_at is None:
            return False, {"passed": False, "reason": "User not found"}

        now = datetime.now(timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_days = (now - created_at).days
        passed = age_days >= 14
        return passed, {
            "passed": passed,
            "account_age_days": age_days,
            "required_days": 14,
        }

    async def _check_receipt_count(self, user_id: str) -> tuple[bool, dict]:
        result = await self.db.execute(
            select(func.count()).where(
                CashbackTransaction.user_id == user_id,
                CashbackTransaction.status == CashbackStatus.CONFIRMED,
                CashbackTransaction.is_referral_reward == False,
            )
        )
        count = result.scalar() or 0
        passed = count >= 5
        return passed, {
            "passed": passed,
            "confirmed_receipts": count,
            "required": 5,
        }

    async def _check_accumulation_period(self, user_id: str) -> tuple[bool, dict]:
        result = await self.db.execute(
            select(
                func.min(CashbackTransaction.created_at),
                func.max(CashbackTransaction.created_at),
            ).where(
                CashbackTransaction.user_id == user_id,
                CashbackTransaction.status == CashbackStatus.CONFIRMED,
            )
        )
        row = result.one_or_none()
        if row is None or row[0] is None:
            return False, {"passed": False, "reason": "No confirmed transactions"}

        first_date, last_date = row
        span_days = (last_date - first_date).days
        passed = span_days >= 7
        return passed, {
            "passed": passed,
            "span_days": span_days,
            "required_days": 7,
        }

    async def _check_grocery_stores(self, user_id: str) -> tuple[bool, dict]:
        """Check that most receipts are from recognized Belgian grocery stores."""
        result = await self.db.execute(
            select(Receipt.store_name).where(
                Receipt.user_id == user_id,
                Receipt.store_name.isnot(None),
            )
        )
        store_names = [row[0] for row in result.all()]

        if not store_names:
            return False, {"passed": False, "reason": "No receipts with store names"}

        recognized = 0
        unrecognized_stores = []
        for name in store_names:
            if name and any(known in name.lower() for known in BELGIAN_GROCERY_STORES):
                recognized += 1
            elif name:
                unrecognized_stores.append(name)

        ratio = recognized / len(store_names) if store_names else 0
        # At least 60% from recognized stores
        passed = ratio >= 0.6
        return passed, {
            "passed": passed,
            "total_receipts": len(store_names),
            "recognized_count": recognized,
            "ratio": round(ratio, 2),
            "unrecognized_samples": unrecognized_stores[:5],
        }

    async def _check_receipt_totals(self, user_id: str) -> tuple[bool, dict]:
        """Check receipt totals are in normal range (EUR 5-300, avg > EUR 15)."""
        result = await self.db.execute(
            select(CashbackTransaction.receipt_total).where(
                CashbackTransaction.user_id == user_id,
                CashbackTransaction.status == CashbackStatus.CONFIRMED,
            )
        )
        totals = [row[0] for row in result.all()]

        if not totals:
            return False, {"passed": False, "reason": "No confirmed transactions"}

        avg_total = sum(totals) / len(totals)
        out_of_range = [t for t in totals if t < 5 or t > 300]
        normal_ratio = (len(totals) - len(out_of_range)) / len(totals)

        # At least 80% in normal range AND average > EUR 15
        passed = normal_ratio >= 0.8 and avg_total > 15
        return passed, {
            "passed": passed,
            "average_total": round(avg_total, 2),
            "total_count": len(totals),
            "out_of_range_count": len(out_of_range),
            "normal_ratio": round(normal_ratio, 2),
        }

    async def _check_no_previous_rejection(self, user_id: str) -> tuple[bool, dict]:
        result = await self.db.execute(
            select(func.count()).where(
                WithdrawalRequest.user_id == user_id,
                WithdrawalRequest.status == WithdrawalStatus.REJECTED,
            )
        )
        count = result.scalar() or 0
        passed = count == 0
        return passed, {"passed": passed, "rejected_count": count}

    async def _check_no_duplicates(self, user_id: str) -> tuple[bool, dict]:
        """Check for suspicious duplicate receipt patterns (same store + total + date)."""
        result = await self.db.execute(
            select(
                Receipt.store_name,
                Receipt.total_amount,
                Receipt.receipt_date,
                func.count().label("cnt"),
            )
            .where(Receipt.user_id == user_id)
            .group_by(Receipt.store_name, Receipt.total_amount, Receipt.receipt_date)
            .having(func.count() > 1)
        )
        duplicates = result.all()
        duplicate_count = len(duplicates)
        passed = duplicate_count <= 1  # Allow 1 coincidental duplicate
        return passed, {
            "passed": passed,
            "duplicate_pattern_count": duplicate_count,
            "max_allowed": 1,
        }

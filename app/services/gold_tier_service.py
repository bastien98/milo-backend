import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.receipt import Receipt
from app.models.enums import ReceiptStatus

logger = logging.getLogger(__name__)

QUALIFYING_AMOUNT = 50.0
QUALIFYING_WINDOW_DAYS = 7
MAX_SPINS = 5

# Cashback tier boundaries (must match CashbackService._TIERS)
_TIER_BOUNDARIES = [
    Decimal("80"),
    Decimal("160"),
    Decimal("240"),
    Decimal("320"),
    Decimal("400"),
    Decimal("500"),
]


async def check_gold_tier(db: AsyncSession, user_id: str) -> bool:
    """Check if user has Gold Tier status.

    Gold Tier if:
    - User has zero completed receipts (new user grace), OR
    - User has at least 1 COMPLETED receipt with total_amount > 50 in last 7 days.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=QUALIFYING_WINDOW_DAYS)

    # Count total completed receipts
    total_q = select(func.count()).select_from(Receipt).where(
        Receipt.user_id == user_id,
        Receipt.status == ReceiptStatus.COMPLETED,
    )
    total_result = await db.execute(total_q)
    total_completed = total_result.scalar() or 0

    if total_completed == 0:
        return True  # New user grace

    # Check for qualifying receipt in last 7 days
    qualifying_q = select(func.count()).select_from(Receipt).where(
        Receipt.user_id == user_id,
        Receipt.status == ReceiptStatus.COMPLETED,
        Receipt.total_amount > QUALIFYING_AMOUNT,
        Receipt.created_at >= cutoff,
    )
    qualifying_result = await db.execute(qualifying_q)
    qualifying_count = qualifying_result.scalar() or 0

    return qualifying_count > 0


def calculate_spins_for_receipt(receipt_total: float) -> int:
    """Calculate spins awarded based on cashback segments covered.

    +1 spin for each segment crossed from €80 onwards.
    €0-€80: 0 spins, €80-€160: 1, €160-€240: 2, €240-€320: 3, €320-€400: 4, €400-€500: 5 (max).
    """
    if receipt_total <= 0:
        return 0

    amount = Decimal(str(receipt_total))

    # +1 spin for each segment crossed from €80 onwards
    spins = 0
    for boundary in _TIER_BOUNDARIES[:-1]:  # skip last boundary (€500 cap)
        if amount > boundary:
            spins += 1
        else:
            break
    return min(spins, MAX_SPINS)

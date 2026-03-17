"""
Tier service for the Milo Points cashback system.

Tier is based on the number of tickets uploaded in the PREVIOUS calendar month.
The tier is determined at the start of each new month and cached on the balance row.

Tiers:
  BRONZE: < 4 tickets/month
  SILVER: 4–9 tickets/month
  GOLD:   10+ tickets/month
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cashback import CashbackBalance
from app.models.enums import TierLevel, ReceiptStatus
from app.models.receipt import Receipt

logger = logging.getLogger(__name__)


def compute_tier(tickets_this_month: int) -> TierLevel:
    """Pure function: compute tier level from ticket count."""
    if tickets_this_month >= 10:
        return TierLevel.GOLD
    if tickets_this_month >= 4:
        return TierLevel.SILVER
    return TierLevel.BRONZE


def _current_month_str() -> str:
    """Return current month as 'YYYY-MM' string."""
    now = datetime.now(timezone.utc)
    return f"{now.year}-{now.month:02d}"


def _previous_month_str() -> str:
    """Return previous calendar month as 'YYYY-MM' string."""
    now = datetime.now(timezone.utc)
    if now.month == 1:
        return f"{now.year - 1}-12"
    return f"{now.year}-{now.month - 1:02d}"


async def _count_receipts_in_month(db: AsyncSession, user_id: str, month_str: str) -> int:
    """Count COMPLETED receipts for a user in the given month ('YYYY-MM')."""
    year, month = int(month_str[:4]), int(month_str[5:])
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(next_year, next_month, 1, tzinfo=timezone.utc)

    result = await db.execute(
        select(func.count()).select_from(Receipt).where(
            Receipt.user_id == user_id,
            Receipt.status == ReceiptStatus.COMPLETED,
            Receipt.created_at >= start,
            Receipt.created_at < end,
        )
    )
    return result.scalar() or 0


async def get_user_tier(db: AsyncSession, balance: CashbackBalance) -> TierLevel:
    """
    Return the user's current tier.

    The tier is based on the PREVIOUS month's ticket count and cached in
    `tier_calculated_month`. If we're now in a new month, recalculate.
    """
    current_month = _current_month_str()

    # Tier is up-to-date for this month — return cached value
    if balance.tier_calculated_month == current_month:
        return balance.tier_level

    # New month — recalculate based on previous month's uploads
    prev_month = _previous_month_str()
    ticket_count = await _count_receipts_in_month(db, balance.user_id, prev_month)
    new_tier = compute_tier(ticket_count)

    balance.tier_level = new_tier
    balance.tier_calculated_month = current_month

    logger.info(
        f"Tier updated for user {balance.user_id}: "
        f"prev_month={prev_month}, tickets={ticket_count}, tier={new_tier.value}"
    )
    return new_tier


async def count_receipts_this_month(db: AsyncSession, user_id: str) -> int:
    """Count completed receipts for the user in the current calendar month."""
    return await _count_receipts_in_month(db, user_id, _current_month_str())


async def count_receipts_today(db: AsyncSession, user_id: str) -> int:
    """Count completed receipts for the user today (UTC date)."""
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    result = await db.execute(
        select(func.count()).select_from(Receipt).where(
            Receipt.user_id == user_id,
            Receipt.status == ReceiptStatus.COMPLETED,
            Receipt.created_at >= start,
            Receipt.created_at <= end,
        )
    )
    return result.scalar() or 0


async def count_receipts_this_iso_week(db: AsyncSession, user_id: str) -> int:
    """Count completed receipts for the user in the current ISO week."""
    now = datetime.now(timezone.utc)
    iso_cal = now.isocalendar()
    # Monday of current ISO week
    monday = datetime.fromisocalendar(iso_cal[0], iso_cal[1], 1).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
    )
    sunday = datetime.fromisocalendar(iso_cal[0], iso_cal[1], 7).replace(
        hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc
    )

    result = await db.execute(
        select(func.count()).select_from(Receipt).where(
            Receipt.user_id == user_id,
            Receipt.status == ReceiptStatus.COMPLETED,
            Receipt.created_at >= monday,
            Receipt.created_at <= sunday,
        )
    )
    return result.scalar() or 0

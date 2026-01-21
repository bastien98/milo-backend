import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.rate_limit_repo import (
    RateLimitRepository,
    RATE_LIMIT_MESSAGES,
    RATE_LIMIT_RECEIPTS,
    RATE_LIMIT_PERIOD_DAYS,
)
from app.db.session import async_session_maker
from app.models.user_rate_limit import UserRateLimit

logger = logging.getLogger(__name__)


@dataclass
class RateLimitStatus:
    """Current rate limit status for a user."""

    allowed: bool
    messages_used: int
    messages_limit: int
    messages_remaining: int
    period_start_date: datetime
    period_end_date: datetime
    days_until_reset: int
    retry_after_seconds: Optional[int] = None
    # Callback to increment counter after successful operation
    _increment_callback: Optional[Callable[[], Awaitable[None]]] = None

    async def increment_on_success(self) -> None:
        """Call this after successful chat completion to increment the counter."""
        if self._increment_callback:
            await self._increment_callback()


@dataclass
class ReceiptRateLimitStatus:
    """Current receipt upload rate limit status for a user."""

    allowed: bool
    receipts_used: int
    receipts_limit: int
    receipts_remaining: int
    period_start_date: datetime
    period_end_date: datetime
    days_until_reset: int
    retry_after_seconds: Optional[int] = None
    # Callback to increment counter after successful operation
    _increment_callback: Optional[Callable[[], Awaitable[None]]] = None

    async def increment_on_success(self) -> None:
        """Call this after successful receipt upload to increment the counter."""
        if self._increment_callback:
            await self._increment_callback()


async def increment_rate_limit_counter(firebase_uid: str) -> None:
    """
    Increment the rate limit counter for a user.

    This function creates its own database session, making it safe to call
    after the original request session has been closed (e.g., in streaming responses).
    """
    async with async_session_maker() as session:
        try:
            repo = RateLimitRepository(session)
            record = await repo.get_by_firebase_uid(firebase_uid)
            if record:
                record.messages_used += 1
                await session.commit()
                logger.debug(f"Incremented rate limit for {firebase_uid}: {record.messages_used}")
            else:
                logger.warning(f"Rate limit record not found for {firebase_uid}")
        except Exception as e:
            logger.error(f"Failed to increment rate limit for {firebase_uid}: {e}")
            await session.rollback()


async def increment_receipt_rate_limit_counter(firebase_uid: str) -> None:
    """
    Increment the receipt upload rate limit counter for a user.

    This function creates its own database session, making it safe to call
    after the original request session has been closed.
    """
    async with async_session_maker() as session:
        try:
            repo = RateLimitRepository(session)
            record = await repo.get_by_firebase_uid(firebase_uid)
            if record:
                record.receipts_used += 1
                await session.commit()
                logger.debug(f"Incremented receipt rate limit for {firebase_uid}: {record.receipts_used}")
            else:
                logger.warning(f"Rate limit record not found for {firebase_uid}")
        except Exception as e:
            logger.error(f"Failed to increment receipt rate limit for {firebase_uid}: {e}")
            await session.rollback()


class RateLimitService:
    """Service for managing user rate limits on AI chat messages."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = RateLimitRepository(db)

    async def get_status(self, firebase_uid: str) -> RateLimitStatus:
        """Get the current rate limit status for a user."""
        record = await self.repo.get_or_create(firebase_uid)

        # Check if period has expired and reset if needed
        now = datetime.now(timezone.utc)
        if now >= record.period_end_date:
            record = await self.repo.reset_period(record)

        return self._build_status(record, firebase_uid=firebase_uid, include_increment_callback=False)

    async def check_rate_limit(self, firebase_uid: str) -> RateLimitStatus:
        """
        Check if a user can send a message.

        Returns a RateLimitStatus with:
        - allowed=True if under limit (call increment_on_success after chat completes)
        - allowed=False if rate limit exceeded
        """
        record = await self.repo.get_or_create(firebase_uid)

        # Check if period has expired and reset if needed
        now = datetime.now(timezone.utc)
        if now >= record.period_end_date:
            record = await self.repo.reset_period(record)

        return self._build_status(record, firebase_uid=firebase_uid, include_increment_callback=True)

    def _build_status(
        self, record: UserRateLimit, firebase_uid: str, include_increment_callback: bool
    ) -> RateLimitStatus:
        """Build a RateLimitStatus from a database record."""
        now = datetime.now(timezone.utc)
        messages_remaining = max(0, RATE_LIMIT_MESSAGES - record.messages_used)
        allowed = record.messages_used < RATE_LIMIT_MESSAGES

        # Calculate days until reset
        time_until_reset = record.period_end_date - now
        days_until_reset = max(0, time_until_reset.days)

        # Calculate retry_after_seconds if rate limited
        retry_after_seconds = None
        if not allowed:
            retry_after_seconds = max(0, int(time_until_reset.total_seconds()))

        # Create increment callback if allowed and requested
        # The callback captures firebase_uid and creates its own session,
        # making it safe to call after the original request session is closed
        increment_callback = None
        if allowed and include_increment_callback:

            async def _callback():
                await increment_rate_limit_counter(firebase_uid)

            increment_callback = _callback

        return RateLimitStatus(
            allowed=allowed,
            messages_used=record.messages_used,
            messages_limit=RATE_LIMIT_MESSAGES,
            messages_remaining=messages_remaining,
            period_start_date=record.period_start_date,
            period_end_date=record.period_end_date,
            days_until_reset=days_until_reset,
            retry_after_seconds=retry_after_seconds,
            _increment_callback=increment_callback,
        )

    async def get_receipt_status(self, firebase_uid: str) -> ReceiptRateLimitStatus:
        """Get the current receipt upload rate limit status for a user."""
        record = await self.repo.get_or_create(firebase_uid)

        # Check if period has expired and reset if needed
        now = datetime.now(timezone.utc)
        if now >= record.period_end_date:
            record = await self.repo.reset_period(record)

        return self._build_receipt_status(record, firebase_uid=firebase_uid, include_increment_callback=False)

    async def check_receipt_rate_limit(self, firebase_uid: str) -> ReceiptRateLimitStatus:
        """
        Check if a user can upload a receipt.

        Returns a ReceiptRateLimitStatus with:
        - allowed=True if under limit (call increment_on_success after upload completes)
        - allowed=False if rate limit exceeded
        """
        record = await self.repo.get_or_create(firebase_uid)

        # Check if period has expired and reset if needed
        now = datetime.now(timezone.utc)
        if now >= record.period_end_date:
            record = await self.repo.reset_period(record)

        return self._build_receipt_status(record, firebase_uid=firebase_uid, include_increment_callback=True)

    def _build_receipt_status(
        self, record: UserRateLimit, firebase_uid: str, include_increment_callback: bool
    ) -> ReceiptRateLimitStatus:
        """Build a ReceiptRateLimitStatus from a database record."""
        now = datetime.now(timezone.utc)
        receipts_remaining = max(0, RATE_LIMIT_RECEIPTS - record.receipts_used)
        allowed = record.receipts_used < RATE_LIMIT_RECEIPTS

        # Calculate days until reset
        time_until_reset = record.period_end_date - now
        days_until_reset = max(0, time_until_reset.days)

        # Calculate retry_after_seconds if rate limited
        retry_after_seconds = None
        if not allowed:
            retry_after_seconds = max(0, int(time_until_reset.total_seconds()))

        # Create increment callback if allowed and requested
        increment_callback = None
        if allowed and include_increment_callback:

            async def _callback():
                await increment_receipt_rate_limit_counter(firebase_uid)

            increment_callback = _callback

        return ReceiptRateLimitStatus(
            allowed=allowed,
            receipts_used=record.receipts_used,
            receipts_limit=RATE_LIMIT_RECEIPTS,
            receipts_remaining=receipts_remaining,
            period_start_date=record.period_start_date,
            period_end_date=record.period_end_date,
            days_until_reset=days_until_reset,
            retry_after_seconds=retry_after_seconds,
            _increment_callback=increment_callback,
        )

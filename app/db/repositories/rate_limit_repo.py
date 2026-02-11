from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_rate_limit import UserRateLimit


RATE_LIMIT_MESSAGES = 100
RATE_LIMIT_RECEIPTS = 999999
RATE_LIMIT_PERIOD_DAYS = 30


class RateLimitRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_firebase_uid(self, firebase_uid: str) -> Optional[UserRateLimit]:
        """Get rate limit record by Firebase UID."""
        result = await self.db.execute(
            select(UserRateLimit).where(UserRateLimit.firebase_uid == firebase_uid)
        )
        return result.scalar_one_or_none()

    async def create(self, firebase_uid: str) -> UserRateLimit:
        """Create a new rate limit record for a user."""
        now = datetime.now(timezone.utc)
        record = UserRateLimit(
            firebase_uid=firebase_uid,
            messages_used=0,
            period_start_date=now,
            period_end_date=now + timedelta(days=RATE_LIMIT_PERIOD_DAYS),
        )
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def get_or_create(self, firebase_uid: str) -> UserRateLimit:
        """Get existing rate limit record or create a new one."""
        record = await self.get_by_firebase_uid(firebase_uid)
        if record is None:
            record = await self.create(firebase_uid)
        return record

    async def reset_period(self, record: UserRateLimit) -> UserRateLimit:
        """Reset the rate limit period for a user."""
        now = datetime.now(timezone.utc)
        record.messages_used = 0
        record.receipts_used = 0
        record.period_start_date = now
        record.period_end_date = now + timedelta(days=RATE_LIMIT_PERIOD_DAYS)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def increment_messages_used(self, record: UserRateLimit) -> UserRateLimit:
        """Increment the messages used counter by 1."""
        record.messages_used += 1
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def increment_receipts_used(self, record: UserRateLimit) -> UserRateLimit:
        """Increment the receipts used counter by 1."""
        record.receipts_used += 1
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def update(self, record: UserRateLimit) -> UserRateLimit:
        """Update a rate limit record."""
        await self.db.flush()
        await self.db.refresh(record)
        return record

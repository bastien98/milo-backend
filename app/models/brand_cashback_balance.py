import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, DateTime, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class BrandCashbackBalance(Base):
    """Per-user EUR-cents ledger for brand cashback only.

    `balance_cents` is the withdrawable amount.
    `total_earned_cents` and `total_withdrawn_cents` are monotonically increasing
    audit counters; `balance_cents` should equal their difference (modulo any
    reserved-but-not-yet-debited withdrawals, which we currently debit upfront).
    """

    __tablename__ = "brand_cashback_balance"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    balance_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    total_earned_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    total_withdrawn_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User")

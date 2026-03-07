import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, DateTime, Boolean, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import ReferralStatus

if TYPE_CHECKING:
    from app.models.user import User


class Referral(Base):
    __tablename__ = "referrals"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    referrer_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    referee_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    referral_code: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[ReferralStatus] = mapped_column(
        SAEnum(ReferralStatus, name="referralstatus",
               values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ReferralStatus.PENDING,
    )
    rewards_granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    referrer_reward_claimed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    referee_reward_claimed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    referrer: Mapped["User"] = relationship(
        "User", foreign_keys=[referrer_id], back_populates="referrals_made"
    )
    referee: Mapped["User"] = relationship(
        "User", foreign_keys=[referee_id]
    )

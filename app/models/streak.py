import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, Float, Integer, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import StreakRewardStatus, StreakRewardType


class StreakReward(Base):
    __tablename__ = "streak_rewards"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reward_type: Mapped[StreakRewardType] = mapped_column(
        SAEnum(StreakRewardType, name="streakrewardtype",
               values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    spins_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cash_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[StreakRewardStatus] = mapped_column(
        SAEnum(StreakRewardStatus, name="streakrewardstatus",
               values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=StreakRewardStatus.CLAIMABLE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user = relationship("User")

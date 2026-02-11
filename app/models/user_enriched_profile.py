from datetime import datetime, date as date_type
from typing import TYPE_CHECKING, Optional, Any

from sqlalchemy import String, DateTime, Date, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class UserEnrichedProfile(Base):
    __tablename__ = "user_enriched_profiles"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )

    # Aggregated shopping habits (JSONB for LLM consumption)
    shopping_habits: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)

    # Up to 25 items of promo interest, categorized
    promo_interest_items: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)

    # Data window
    data_period_start: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    data_period_end: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)
    receipts_analyzed: Mapped[int] = mapped_column(Integer, default=0)

    # Rebuild tracking
    last_rebuilt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="enriched_profile")

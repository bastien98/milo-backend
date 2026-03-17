import uuid
from datetime import datetime
from datetime import date as date_type
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.promo_report_event import PromoReportEvent


class PromoWeeklyCandidates(Base):
    __tablename__ = "promo_weekly_candidates"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    iso_year: Mapped[int] = mapped_column(Integer, nullable=False)
    iso_week: Mapped[int] = mapped_column(Integer, nullable=False)
    report_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    candidates_json: Mapped[Any] = mapped_column(JSONB, nullable=False)
    closing_nudge: Mapped[str] = mapped_column(Text, nullable=False, default="")
    smart_switch_json: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    store_tips_json: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    interest_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_matches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "iso_week >= 1 AND iso_week <= 53",
            name="ck_promo_weekly_candidates_iso_week_range",
        ),
        UniqueConstraint(
            "user_id",
            "iso_year",
            "iso_week",
            name="uq_promo_weekly_candidates_user_week",
        ),
    )

    user: Mapped["User"] = relationship("User", back_populates="promo_weekly_candidates")
    events: Mapped[list["PromoReportEvent"]] = relationship(
        "PromoReportEvent",
        back_populates="candidates",
        cascade="all, delete-orphan",
    )

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import PromoReportEventType

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.promo_weekly_candidates import PromoWeeklyCandidates


class PromoReportEvent(Base):
    __tablename__ = "promo_report_events"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    report_id: Mapped[str] = mapped_column(
        String, ForeignKey("promo_weekly_candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    iso_year: Mapped[int] = mapped_column(Integer, nullable=False)
    iso_week: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[PromoReportEventType] = mapped_column(
        SAEnum(PromoReportEventType, native_enum=False),
        nullable=False,
    )
    item_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    store_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    metadata_json: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    __table_args__ = (
        CheckConstraint("iso_week >= 1 AND iso_week <= 53", name="ck_promo_report_events_iso_week_range"),
    )

    candidates: Mapped["PromoWeeklyCandidates"] = relationship("PromoWeeklyCandidates", back_populates="events")
    user: Mapped["User"] = relationship("User", back_populates="promo_report_events")

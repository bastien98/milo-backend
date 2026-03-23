import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import PromoReportEventType

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.promo_candidates import PromoCandidates


class PromoReportEvent(Base):
    __tablename__ = "promo_report_events"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    report_id: Mapped[str] = mapped_column(
        String, ForeignKey("promo_candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
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

    candidates: Mapped["PromoCandidates"] = relationship("PromoCandidates", back_populates="events")
    user: Mapped["User"] = relationship("User", back_populates="promo_report_events")

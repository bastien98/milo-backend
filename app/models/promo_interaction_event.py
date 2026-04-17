import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class PromoInteractionEvent(Base):
    __tablename__ = "promo_interaction_events"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    promo_item_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_item_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    store_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[Optional["User"]] = relationship(
        "User", back_populates="promo_interaction_events"
    )

    __table_args__ = (
        Index("ix_promo_interaction_events_user_id", "user_id"),
        Index("ix_promo_interaction_events_promo_item_id", "promo_item_id"),
        Index("ix_promo_interaction_events_event_created", "event_type", "created_at"),
    )

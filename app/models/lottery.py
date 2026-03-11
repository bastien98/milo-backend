import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, DateTime, Integer, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import LotteryDrawingStatus

if TYPE_CHECKING:
    from app.models.user import User


class LotteryDrawing(Base):
    __tablename__ = "lottery_drawings"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    month: Mapped[str] = mapped_column(String(7), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=LotteryDrawingStatus.PENDING.value)
    prize_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=10000)
    seed: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    seed_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    winner_user_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    winner_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    winner_instagram_handle: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    participant_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    post_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    instagram_post_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    drawn_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    entries: Mapped[list["LotteryEntry"]] = relationship("LotteryEntry", back_populates="drawing", cascade="all, delete-orphan")
    winner: Mapped[Optional["User"]] = relationship("User", foreign_keys=[winner_user_id])


class LotteryEntry(Base):
    __tablename__ = "lottery_entries"
    __table_args__ = (
        UniqueConstraint("drawing_id", "user_id", name="uq_lottery_entry_drawing_user"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    drawing_id: Mapped[str] = mapped_column(
        String, ForeignKey("lottery_drawings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    instagram_handle: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    has_receipt_activity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_instagram_share: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    proof_image_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    proof_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # pending_review, approved, rejected
    entry_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    drawing: Mapped["LotteryDrawing"] = relationship("LotteryDrawing", back_populates="entries")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])

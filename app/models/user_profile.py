from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Integer, DateTime, Boolean, Enum as SQLEnum, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import Gender, Language

if TYPE_CHECKING:
    from app.models.user import User


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.firebase_uid", ondelete="CASCADE"),
        primary_key=True
    )
    first_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    nickname: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    gender: Mapped[Optional[Gender]] = mapped_column(
        SQLEnum(Gender, native_enum=False), nullable=True
    )
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    language: Mapped[Optional[Language]] = mapped_column(
        SQLEnum(Language, native_enum=False), nullable=True
    )
    preferred_stores: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    referral_code: Mapped[Optional[str]] = mapped_column(String(10), unique=True, nullable=True, index=True)
    referred_by_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    iban: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    iban_last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    profile_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="profile")

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional, List
from enum import Enum

from sqlalchemy import String, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.bank_account import BankAccount


class BankConnectionStatus(str, Enum):
    """Status of a bank connection."""

    PENDING = "pending"  # Authorization started, waiting for callback
    ACTIVE = "active"  # Connection active and valid
    EXPIRED = "expired"  # Consent expired
    REVOKED = "revoked"  # User revoked consent
    ERROR = "error"  # Connection error


class CallbackType(str, Enum):
    """Type of callback for OAuth redirect."""

    WEB = "web"  # Redirect to web frontend
    MOBILE = "mobile"  # Redirect to mobile app via deep link


class BankConnection(Base):
    __tablename__ = "bank_connections"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # EnableBanking identifiers
    session_id: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)
    aspsp_name: Mapped[str] = mapped_column(String, nullable=False)  # Bank name
    aspsp_country: Mapped[str] = mapped_column(String(2), nullable=False)  # ISO 3166-1 alpha-2

    # Authorization state (used during OAuth flow)
    auth_state: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    callback_type: Mapped[CallbackType] = mapped_column(
        String, default=CallbackType.WEB, nullable=False
    )

    # Connection status
    status: Mapped[BankConnectionStatus] = mapped_column(
        String, default=BankConnectionStatus.PENDING, nullable=False
    )

    # Consent validity
    valid_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Error details (if status is ERROR)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Raw EnableBanking response (for debugging)
    raw_response: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="bank_connections")
    accounts: Mapped[List["BankAccount"]] = relationship(
        "BankAccount", back_populates="connection", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_bank_connections_user_status", "user_id", "status"),
    )

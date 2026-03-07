import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, DateTime, Float, Boolean, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import WithdrawalStatus

if TYPE_CHECKING:
    from app.models.user import User


class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_requests"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    iban: Mapped[str] = mapped_column(String, nullable=False)
    iban_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[WithdrawalStatus] = mapped_column(
        SAEnum(WithdrawalStatus, name="withdrawalstatus",
               values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=WithdrawalStatus.PENDING_REVIEW,
    )
    fraud_check_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fraud_check_details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    admin_notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_out_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    wise_transfer_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="withdrawal_requests")

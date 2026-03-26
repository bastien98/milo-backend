import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, DateTime, Float, Boolean, ForeignKey, Enum as SAEnum, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import CharityDonationStatus

if TYPE_CHECKING:
    from app.models.user import User


class CharityDonation(Base):
    __tablename__ = "charity_donations"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    charity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    charity_name: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)

    status: Mapped[CharityDonationStatus] = mapped_column(
        SAEnum(CharityDonationStatus, name="charitydonationstatus",
               values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=CharityDonationStatus.PENDING,
    )

    fraud_check_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fraud_check_details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    transferred_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User")

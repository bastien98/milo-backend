import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, DateTime, Float, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import CashbackStatus

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.receipt import Receipt


class CashbackTransaction(Base):
    __tablename__ = "cashback_transactions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    receipt_id: Mapped[str] = mapped_column(
        String, ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    receipt_total: Mapped[float] = mapped_column(Float, nullable=False)
    cashback_amount: Mapped[float] = mapped_column(Float, nullable=False)
    effective_rate: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[CashbackStatus] = mapped_column(
        SAEnum(CashbackStatus, name="cashbackstatus",
               values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=CashbackStatus.CONFIRMED,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="cashback_transactions")
    receipt: Mapped["Receipt"] = relationship("Receipt")


class CashbackBalance(Base):
    __tablename__ = "cashback_balances"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    total_earned: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_paid_out: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    current_balance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="cashback_balance")

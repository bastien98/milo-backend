import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, DateTime, Integer, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.receipt import Receipt


class BrandCashbackCampaign(Base):
    __tablename__ = "brand_cashback_campaigns"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    brand_name: Mapped[str] = mapped_column(String, nullable=False)
    product_name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    cashback_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    image_s3_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    eligible_stores: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    requires_store: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    terms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    how_it_works: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="'[]'::jsonb")
    claim_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14, server_default="14")
    max_redemptions_per_user: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    total_redemption_cap: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Relationships
    line_items: Mapped[list["BrandCashbackStoreLineItem"]] = relationship(
        "BrandCashbackStoreLineItem", back_populates="campaign", cascade="all, delete-orphan"
    )
    claims: Mapped[list["UserBrandCashbackClaim"]] = relationship(
        "UserBrandCashbackClaim", back_populates="campaign", cascade="all, delete-orphan"
    )


class BrandCashbackStoreLineItem(Base):
    __tablename__ = "brand_cashback_store_line_items"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    campaign_id: Mapped[str] = mapped_column(
        String, ForeignKey("brand_cashback_campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    store_name: Mapped[str] = mapped_column(String, nullable=False)
    exact_line_item: Mapped[str] = mapped_column(String, nullable=False)
    alt_line_items: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    campaign: Mapped["BrandCashbackCampaign"] = relationship("BrandCashbackCampaign", back_populates="line_items")


class UserBrandCashbackClaim(Base):
    __tablename__ = "user_brand_cashback_claims"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[str] = mapped_column(
        String, ForeignKey("brand_cashback_campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="claimed")
    receipt_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("receipts.id", ondelete="SET NULL"), nullable=True
    )
    matched_line_item_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("brand_cashback_store_line_items.id", ondelete="SET NULL"), nullable=True
    )
    cashback_earned_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    earned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User")
    campaign: Mapped["BrandCashbackCampaign"] = relationship("BrandCashbackCampaign", back_populates="claims")
    receipt: Mapped[Optional["Receipt"]] = relationship("Receipt")

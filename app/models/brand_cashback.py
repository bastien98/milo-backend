import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, DateTime, Integer, Boolean, ForeignKey, Text, Float, UniqueConstraint
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
    image_thumb_s3_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    eligible_stores: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    requires_store: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    terms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    how_it_works: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="'[]'::jsonb")
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
    claims: Mapped[list["BrandCashbackClaim"]] = relationship(
        "BrandCashbackClaim", back_populates="campaign", cascade="all, delete-orphan"
    )
    earnings: Mapped[list["BrandCashbackEarning"]] = relationship(
        "BrandCashbackEarning", back_populates="campaign", cascade="all, delete-orphan"
    )
    pending_matches: Mapped[list["BrandCashbackPendingMatch"]] = relationship(
        "BrandCashbackPendingMatch", back_populates="campaign", cascade="all, delete-orphan"
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
    product_codes: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    campaign: Mapped["BrandCashbackCampaign"] = relationship("BrandCashbackCampaign", back_populates="line_items")


class BrandCashbackClaim(Base):
    """Persistent intent: the user wants to earn this cashback.

    One row per (user, campaign). Created on POST /claim, deleted on DELETE /claim,
    consulted on every receipt upload to know which campaigns to match against.
    """

    __tablename__ = "brand_cashback_claims"
    __table_args__ = (
        UniqueConstraint("user_id", "campaign_id", name="uq_brand_cashback_claims_user_campaign"),
    )

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
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User")
    campaign: Mapped["BrandCashbackCampaign"] = relationship("BrandCashbackCampaign", back_populates="claims")


class BrandCashbackEarning(Base):
    """One row per successful receipt match — the actual reward event.

    Many earnings can exist per (user, campaign), capped by
    BrandCashbackCampaign.max_redemptions_per_user.
    """

    __tablename__ = "brand_cashback_earnings"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[str] = mapped_column(
        String, ForeignKey("brand_cashback_campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    receipt_id: Mapped[str] = mapped_column(
        String, ForeignKey("receipts.id", ondelete="SET NULL"), nullable=False
    )
    matched_line_item_id: Mapped[str] = mapped_column(
        String, ForeignKey("brand_cashback_store_line_items.id", ondelete="SET NULL"), nullable=False
    )
    cashback_earned_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    earned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User")
    campaign: Mapped["BrandCashbackCampaign"] = relationship("BrandCashbackCampaign", back_populates="earnings")
    receipt: Mapped[Optional["Receipt"]] = relationship("Receipt")


class BrandCashbackPendingMatch(Base):
    """A receipt that fuzzy-matched a claimed campaign but didn't pass strict equality.

    Created by check_receipt_for_brand_cashback when no exact match is found
    but the best fuzzy score is >= QUEUE_THRESHOLD. Reviewed by an admin who
    either approves (creates an earning + optionally extends alt_line_items)
    or denies (with a reason shown to the user).
    """

    __tablename__ = "brand_cashback_pending_matches"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "campaign_id",
            "receipt_id",
            name="uq_brand_cashback_pending_user_campaign_receipt",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[str] = mapped_column(
        String, ForeignKey("brand_cashback_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    receipt_id: Mapped[str] = mapped_column(
        String, ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False
    )
    candidate_string: Mapped[str] = mapped_column(Text, nullable=False)
    matched_line_item_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("brand_cashback_store_line_items.id", ondelete="SET NULL"), nullable=True
    )
    match_score: Mapped[float] = mapped_column(Float, nullable=False)
    store_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    denial_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    earning_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("brand_cashback_earnings.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    campaign: Mapped["BrandCashbackCampaign"] = relationship(
        "BrandCashbackCampaign", back_populates="pending_matches"
    )
    receipt: Mapped[Optional["Receipt"]] = relationship("Receipt")
    matched_line_item: Mapped[Optional["BrandCashbackStoreLineItem"]] = relationship(
        "BrandCashbackStoreLineItem"
    )
    earning: Mapped[Optional["BrandCashbackEarning"]] = relationship(
        "BrandCashbackEarning", foreign_keys=[earning_id]
    )

import uuid
from datetime import datetime
from datetime import date as date_type
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class PromoItem(Base):
    __tablename__ = "promo_items"

    id: Mapped[str] = mapped_column(
        String, primary_key=True
    )
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    display_name_lower: Mapped[str] = mapped_column(String, nullable=False)
    display_mechanism: Mapped[str] = mapped_column(String, nullable=False)
    display_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    display_savings_label: Mapped[str] = mapped_column(String, nullable=False, default="")
    display_unit_price: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Unit pricing — numeric fields derived in Python from pack_size_* (see promo_folders_pipelines.unit_pricing)
    unit_price_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit_price_unit: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    pack_size_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pack_size_unit: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    pack_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    unit_price_quality: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    normalized_brand: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    display_brand: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    original_price: Mapped[float] = mapped_column(Float, nullable=False)
    promo_price: Mapped[float] = mapped_column(Float, nullable=False)
    savings_amount: Mapped[float] = mapped_column(Float, nullable=False)
    min_purchase_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    promo_depth: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    granular_category: Mapped[str] = mapped_column(String(100), nullable=False)
    source_retailer: Mapped[str] = mapped_column(String, nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False, default="folder")
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    promo_folder_url: Mapped[str] = mapped_column(Text, nullable=False)

    validity_start: Mapped[date_type] = mapped_column(Date, nullable=False)
    validity_end: Mapped[date_type] = mapped_column(Date, nullable=False)

    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hero_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Bounding boxes (normalized 0-1 coordinates)
    bbox_x_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bbox_y_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bbox_x_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bbox_y_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tile_bbox_x_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tile_bbox_y_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tile_bbox_x_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tile_bbox_y_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_promo_items_source_retailer", "source_retailer"),
        Index("ix_promo_items_granular_category", "granular_category"),
        Index("ix_promo_items_validity", "validity_start", "validity_end"),
        Index("ix_promo_items_unit_price", "granular_category", "unit_price_unit", "unit_price_value"),
    )

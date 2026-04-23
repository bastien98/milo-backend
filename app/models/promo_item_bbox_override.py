from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class PromoItemBboxOverride(Base):
    """Manual bbox correction that wins over extractor output on every re-ingest.

    Keyed on (promo_folder_url, page_number, display_name_normalized) because that
    triple is stable across re-ingestions of the same source PDF. Lowercased/trimmed
    display_name matches the same normalization the pipeline performs before lookup.
    """

    __tablename__ = "promo_item_bbox_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    promo_folder_url: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name_normalized: Mapped[str] = mapped_column(Text, nullable=False)

    tile_bbox_x_min: Mapped[float] = mapped_column(Float, nullable=False)
    tile_bbox_y_min: Mapped[float] = mapped_column(Float, nullable=False)
    tile_bbox_x_max: Mapped[float] = mapped_column(Float, nullable=False)
    tile_bbox_y_max: Mapped[float] = mapped_column(Float, nullable=False)

    # Product-only bbox. When NULL, bbox falls back to tile_bbox at apply time.
    bbox_x_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bbox_y_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bbox_x_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bbox_y_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "promo_folder_url",
            "page_number",
            "display_name_normalized",
            name="uq_promo_item_bbox_overrides_folder_page_name",
        ),
        Index(
            "ix_promo_item_bbox_overrides_folder_page",
            "promo_folder_url",
            "page_number",
        ),
    )

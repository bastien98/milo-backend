"""Add promo weekly report tables

Revision ID: 046_add_promo_weekly_report_tables
Revises: 045_add_dp_product_name_no_brand
Create Date: 2026-03-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "046_add_promo_weekly_report_tables"
down_revision: str = "045_add_dp_product_name_no_brand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promo_weekly_reports",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("iso_year", sa.Integer(), nullable=False),
        sa.Column("iso_week", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("receipts_analyzed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("profile_period_start", sa.Date(), nullable=True),
        sa.Column("profile_period_end", sa.Date(), nullable=True),
        sa.Column("deal_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("weekly_savings", sa.Float(), nullable=False, server_default="0"),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("iso_week >= 1 AND iso_week <= 53", name="ck_promo_weekly_reports_iso_week_range"),
        sa.CheckConstraint("receipts_analyzed >= 0", name="ck_promo_weekly_reports_receipts_non_negative"),
        sa.CheckConstraint("deal_count >= 0", name="ck_promo_weekly_reports_deal_count_non_negative"),
        sa.CheckConstraint("weekly_savings >= 0", name="ck_promo_weekly_reports_weekly_savings_non_negative"),
        sa.CheckConstraint(
            "profile_period_start IS NULL OR profile_period_end IS NULL OR profile_period_start <= profile_period_end",
            name="ck_promo_weekly_reports_profile_period_order",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "iso_year", "iso_week", name="uq_promo_weekly_reports_user_week"),
    )
    op.create_index(
        "ix_promo_weekly_reports_user_id",
        "promo_weekly_reports",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "promo_report_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("report_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("iso_year", sa.Integer(), nullable=False),
        sa.Column("iso_week", sa.Integer(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "report_viewed",
                "deal_opened",
                "folder_opened",
                "store_section_opened",
                "feedback_positive",
                "feedback_negative",
                name="promoreporteventtype",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("item_key", sa.String(length=64), nullable=True),
        sa.Column("store_name", sa.String(length=255), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("iso_week >= 1 AND iso_week <= 53", name="ck_promo_report_events_iso_week_range"),
        sa.ForeignKeyConstraint(["report_id"], ["promo_weekly_reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_promo_report_events_report_id", "promo_report_events", ["report_id"], unique=False)
    op.create_index("ix_promo_report_events_user_id", "promo_report_events", ["user_id"], unique=False)
    op.create_index("ix_promo_report_events_item_key", "promo_report_events", ["item_key"], unique=False)
    op.create_index("ix_promo_report_events_store_name", "promo_report_events", ["store_name"], unique=False)
    op.create_index("ix_promo_report_events_created_at", "promo_report_events", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_promo_report_events_created_at", table_name="promo_report_events")
    op.drop_index("ix_promo_report_events_store_name", table_name="promo_report_events")
    op.drop_index("ix_promo_report_events_item_key", table_name="promo_report_events")
    op.drop_index("ix_promo_report_events_user_id", table_name="promo_report_events")
    op.drop_index("ix_promo_report_events_report_id", table_name="promo_report_events")
    op.drop_table("promo_report_events")
    op.drop_index("ix_promo_weekly_reports_user_id", table_name="promo_weekly_reports")
    op.drop_table("promo_weekly_reports")

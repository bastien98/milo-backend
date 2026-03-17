"""Replace promo_weekly_reports with promo_weekly_candidates and fix preferred_stores

Revision ID: 047_promo_candidates_and_preferred_stores
Revises: 046_add_promo_weekly_report_tables
Create Date: 2026-03-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "047_promo_candidates_and_preferred_stores"
down_revision: str = "046_add_promo_weekly_report_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create promo_weekly_candidates table
    op.create_table(
        "promo_weekly_candidates",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("iso_year", sa.Integer(), nullable=False),
        sa.Column("iso_week", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("candidates_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("closing_nudge", sa.Text(), nullable=False, server_default=""),
        sa.Column("smart_switch_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("store_tips_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("interest_item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_matches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "iso_week >= 1 AND iso_week <= 53",
            name="ck_promo_weekly_candidates_iso_week_range",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "iso_year", "iso_week",
            name="uq_promo_weekly_candidates_user_week",
        ),
    )
    op.create_index(
        "ix_promo_weekly_candidates_user_id",
        "promo_weekly_candidates",
        ["user_id"],
        unique=False,
    )

    # 2. Re-point promo_report_events FK from promo_weekly_reports to promo_weekly_candidates
    op.drop_constraint(
        "promo_report_events_report_id_fkey",
        "promo_report_events",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "promo_report_events_report_id_fkey",
        "promo_report_events",
        "promo_weekly_candidates",
        ["report_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 3. Drop promo_weekly_reports table
    op.drop_index("ix_promo_weekly_reports_user_id", table_name="promo_weekly_reports")
    op.drop_table("promo_weekly_reports")

    # 4. Make preferred_stores non-null with default []
    op.execute("UPDATE user_profiles SET preferred_stores = '[]'::jsonb WHERE preferred_stores IS NULL")
    op.alter_column(
        "user_profiles",
        "preferred_stores",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
        server_default="[]",
    )


def downgrade() -> None:
    # 1. Revert preferred_stores to nullable
    op.alter_column(
        "user_profiles",
        "preferred_stores",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
        server_default=None,
    )

    # 2. Recreate promo_weekly_reports table
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
    op.create_index("ix_promo_weekly_reports_user_id", "promo_weekly_reports", ["user_id"], unique=False)

    # 3. Re-point FK back to promo_weekly_reports
    op.drop_constraint(
        "promo_report_events_report_id_fkey",
        "promo_report_events",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "promo_report_events_report_id_fkey",
        "promo_report_events",
        "promo_weekly_reports",
        ["report_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 4. Drop promo_weekly_candidates
    op.drop_index("ix_promo_weekly_candidates_user_id", table_name="promo_weekly_candidates")
    op.drop_table("promo_weekly_candidates")

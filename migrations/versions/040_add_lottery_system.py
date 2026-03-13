"""Add lottery system tables and instagram_handle to user_profiles

Revision ID: 040_add_lottery_system
Revises: 039_add_geo_and_itsme_fields
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa

revision: str = "040_add_lottery_system"
down_revision: str = "039_add_geo_and_itsme_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add instagram_handle to user_profiles
    op.add_column("user_profiles", sa.Column("instagram_handle", sa.String(30), nullable=True))
    op.create_index(op.f("ix_user_profiles_instagram_handle"), "user_profiles", ["instagram_handle"])

    # Create lottery_drawings table
    op.create_table(
        "lottery_drawings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("month", sa.String(7), nullable=False, unique=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("prize_amount_cents", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("seed", sa.String(64), nullable=True),
        sa.Column("seed_hash", sa.String(64), nullable=True),
        sa.Column("winner_user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("winner_name", sa.String(), nullable=True),
        sa.Column("winner_instagram_handle", sa.String(), nullable=True),
        sa.Column("participant_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("video_url", sa.String(), nullable=True),
        sa.Column("instagram_post_id", sa.String(), nullable=True),
        sa.Column("drawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(op.f("ix_lottery_drawings_month"), "lottery_drawings", ["month"], unique=True)

    # Create lottery_entries table
    op.create_table(
        "lottery_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("drawing_id", sa.String(), sa.ForeignKey("lottery_drawings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instagram_handle", sa.String(30), nullable=True),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("has_receipt_activity", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("has_instagram_share", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_eligible", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("entry_number", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(op.f("ix_lottery_entries_drawing_id"), "lottery_entries", ["drawing_id"])
    op.create_index(op.f("ix_lottery_entries_user_id"), "lottery_entries", ["user_id"])
    op.create_unique_constraint("uq_lottery_entry_drawing_user", "lottery_entries", ["drawing_id", "user_id"])


def downgrade() -> None:
    op.drop_constraint("uq_lottery_entry_drawing_user", "lottery_entries")
    op.drop_index(op.f("ix_lottery_entries_user_id"), table_name="lottery_entries")
    op.drop_index(op.f("ix_lottery_entries_drawing_id"), table_name="lottery_entries")
    op.drop_table("lottery_entries")
    op.drop_index(op.f("ix_lottery_drawings_month"), table_name="lottery_drawings")
    op.drop_table("lottery_drawings")
    op.drop_index(op.f("ix_user_profiles_instagram_handle"), table_name="user_profiles")
    op.drop_column("user_profiles", "instagram_handle")

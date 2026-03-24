"""Simplify promo_weekly_candidates to one row per user (no weekly history)

Revision ID: 049_simplify_promo_candidates_one_per_user
Revises: 048_migrate_to_milo_points
Create Date: 2026-03-23

Changes:
- Delete duplicate candidate rows, keeping only the latest per user
- Drop iso_year, iso_week columns and constraints from promo_weekly_candidates
- Add unique constraint on user_id alone
- Drop iso_year, iso_week columns and constraint from promo_report_events
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "049_simplify_promo_candidates_one_per_user"
down_revision = "048_migrate_to_milo_points"
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    return conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = :t)"
        ),
        {"t": table_name},
    ).scalar()


def upgrade() -> None:
    conn = op.get_bind()
    candidates_exists = _table_exists(conn, "promo_weekly_candidates")
    events_exists = _table_exists(conn, "promo_report_events")

    if candidates_exists:
        # 1. Keep only the latest candidate row per user (CASCADE deletes orphaned events)
        op.execute("""
            DELETE FROM promo_weekly_candidates
            WHERE id NOT IN (
                SELECT DISTINCT ON (user_id) id
                FROM promo_weekly_candidates
                ORDER BY user_id, generated_at DESC
            )
        """)

        # 2. Drop old constraints from promo_weekly_candidates
        op.drop_constraint(
            "uq_promo_weekly_candidates_user_week",
            "promo_weekly_candidates",
            type_="unique",
        )
        op.drop_constraint(
            "ck_promo_weekly_candidates_iso_week_range",
            "promo_weekly_candidates",
            type_="check",
        )

        # 3. Drop iso_year, iso_week columns from promo_weekly_candidates
        op.drop_column("promo_weekly_candidates", "iso_year")
        op.drop_column("promo_weekly_candidates", "iso_week")

        # 4. Add unique constraint on user_id alone
        op.create_unique_constraint(
            "uq_promo_candidates_user_id",
            "promo_weekly_candidates",
            ["user_id"],
        )
    else:
        # Table was never created — build it directly with the post-049 schema
        op.create_table(
            "promo_weekly_candidates",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
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
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", name="uq_promo_candidates_user_id"),
        )
        op.create_index(
            "ix_promo_weekly_candidates_user_id",
            "promo_weekly_candidates",
            ["user_id"],
            unique=False,
        )

    if events_exists:
        # 5. Drop constraint and columns from promo_report_events
        op.drop_constraint(
            "ck_promo_report_events_iso_week_range",
            "promo_report_events",
            type_="check",
        )
        op.drop_column("promo_report_events", "iso_year")
        op.drop_column("promo_report_events", "iso_week")
    else:
        # Table was never created — build it directly with the post-049 schema
        op.create_table(
            "promo_report_events",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("report_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
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
            sa.ForeignKeyConstraint(["report_id"], ["promo_weekly_candidates.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_promo_report_events_report_id", "promo_report_events", ["report_id"], unique=False)
        op.create_index("ix_promo_report_events_user_id", "promo_report_events", ["user_id"], unique=False)
        op.create_index("ix_promo_report_events_item_key", "promo_report_events", ["item_key"], unique=False)
        op.create_index("ix_promo_report_events_store_name", "promo_report_events", ["store_name"], unique=False)
        op.create_index("ix_promo_report_events_created_at", "promo_report_events", ["created_at"], unique=False)


def downgrade() -> None:
    # Re-add columns to promo_report_events
    op.add_column(
        "promo_report_events",
        sa.Column("iso_year", sa.Integer(), nullable=True),
    )
    op.add_column(
        "promo_report_events",
        sa.Column("iso_week", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_promo_report_events_iso_week_range",
        "promo_report_events",
        "iso_week >= 1 AND iso_week <= 53",
    )

    # Re-add columns to promo_weekly_candidates
    op.drop_constraint(
        "uq_promo_candidates_user_id",
        "promo_weekly_candidates",
        type_="unique",
    )
    op.add_column(
        "promo_weekly_candidates",
        sa.Column("iso_year", sa.Integer(), nullable=True),
    )
    op.add_column(
        "promo_weekly_candidates",
        sa.Column("iso_week", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_promo_weekly_candidates_iso_week_range",
        "promo_weekly_candidates",
        "iso_week >= 1 AND iso_week <= 53",
    )
    op.create_unique_constraint(
        "uq_promo_weekly_candidates_user_week",
        "promo_weekly_candidates",
        ["user_id", "iso_year", "iso_week"],
    )

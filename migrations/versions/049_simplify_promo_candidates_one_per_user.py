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


revision = "049_simplify_promo_candidates_one_per_user"
down_revision = "048_migrate_to_milo_points"
branch_labels = None
depends_on = None


def upgrade() -> None:
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

    # 5. Drop constraint and columns from promo_report_events
    op.drop_constraint(
        "ck_promo_report_events_iso_week_range",
        "promo_report_events",
        type_="check",
    )
    op.drop_column("promo_report_events", "iso_year")
    op.drop_column("promo_report_events", "iso_week")


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

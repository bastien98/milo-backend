"""Rename promo_weekly_candidates table to promo_candidates

Revision ID: 050_rename_promo_weekly_candidates
Revises: 049_simplify_promo_candidates_one_per_user
Create Date: 2026-03-23

Changes:
- Rename table promo_weekly_candidates → promo_candidates
- Rename index ix_promo_weekly_candidates_user_id → ix_promo_candidates_user_id
- FK on promo_report_events.report_id automatically follows the table rename
"""

revision = "050_rename_promo_weekly_candidates"
down_revision = "049_simplify_promo_candidates_one_per_user"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    op.rename_table("promo_weekly_candidates", "promo_candidates")
    op.execute(
        "ALTER INDEX ix_promo_weekly_candidates_user_id "
        "RENAME TO ix_promo_candidates_user_id"
    )


def downgrade() -> None:
    op.rename_table("promo_candidates", "promo_weekly_candidates")
    op.execute(
        "ALTER INDEX ix_promo_candidates_user_id "
        "RENAME TO ix_promo_weekly_candidates_user_id"
    )

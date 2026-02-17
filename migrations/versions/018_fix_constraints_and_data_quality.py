"""Fix FK constraints, indexes, CHECK constraints, and nullable timestamps

Revision ID: 018_fix_constraints
Revises: 017_fix_budget_id_defaults
Create Date: 2026-02-17

Fixes:
- Add ON DELETE CASCADE to receipts.user_id, transactions.user_id (were NO ACTION)
- Add FK constraint on user_rate_limits.firebase_uid -> users.firebase_uid
- Drop duplicate index on budget_history (user_id, month)
- Add CHECK constraints for data validation
- Make timestamp columns with server defaults NOT NULL
"""
from typing import Sequence, Union

from alembic import op


revision: str = '018_fix_constraints'
down_revision: Union[str, None] = '017_fix_budget_id_defaults'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ──────────────────────────────────────────────────────────────────────
    # 1. Fix ON DELETE CASCADE on receipts.user_id (was NO ACTION)
    # ──────────────────────────────────────────────────────────────────────
    op.drop_constraint("receipts_user_id_fkey", "receipts", type_="foreignkey")
    op.create_foreign_key(
        "receipts_user_id_fkey", "receipts", "users",
        ["user_id"], ["id"], ondelete="CASCADE"
    )

    # ──────────────────────────────────────────────────────────────────────
    # 2. Fix ON DELETE CASCADE on transactions.user_id (was NO ACTION)
    # ──────────────────────────────────────────────────────────────────────
    op.drop_constraint("transactions_user_id_fkey", "transactions", type_="foreignkey")
    op.create_foreign_key(
        "transactions_user_id_fkey", "transactions", "users",
        ["user_id"], ["id"], ondelete="CASCADE"
    )

    # ──────────────────────────────────────────────────────────────────────
    # 3. Add FK on user_rate_limits.firebase_uid -> users.firebase_uid
    # ──────────────────────────────────────────────────────────────────────
    op.create_foreign_key(
        "user_rate_limits_firebase_uid_fkey", "user_rate_limits", "users",
        ["firebase_uid"], ["firebase_uid"], ondelete="CASCADE"
    )

    # ──────────────────────────────────────────────────────────────────────
    # 4. Drop duplicate index on budget_history (user_id, month)
    #    The unique constraint uq_budget_history_user_month already provides
    #    an index on (user_id, month).
    # ──────────────────────────────────────────────────────────────────────
    op.drop_index("idx_budget_history_user_month", table_name="budget_history")

    # ──────────────────────────────────────────────────────────────────────
    # 5. CHECK constraints for data validation
    # ──────────────────────────────────────────────────────────────────────
    op.create_check_constraint(
        "ck_transactions_health_score_range", "transactions",
        "health_score >= 0 AND health_score <= 5"
    )
    op.create_check_constraint(
        "ck_transactions_quantity_non_negative", "transactions",
        "quantity >= 0"
    )
    op.create_check_constraint(
        "ck_budgets_monthly_amount_positive", "budgets",
        "monthly_amount > 0"
    )

    # ──────────────────────────────────────────────────────────────────────
    # 6. Make nullable timestamps NOT NULL (all have server_default=now())
    # ──────────────────────────────────────────────────────────────────────
    # First backfill any NULLs with now()
    op.execute("UPDATE budget_history SET created_at = now() WHERE created_at IS NULL")
    op.execute("UPDATE budgets SET created_at = now() WHERE created_at IS NULL")
    op.execute("UPDATE budgets SET updated_at = now() WHERE updated_at IS NULL")
    op.execute("UPDATE expense_splits SET created_at = now() WHERE created_at IS NULL")
    op.execute("UPDATE recent_friends SET last_used_at = now() WHERE last_used_at IS NULL")
    op.execute("UPDATE recent_friends SET use_count = 1 WHERE use_count IS NULL")

    op.alter_column("budget_history", "created_at", nullable=False)
    op.alter_column("budgets", "created_at", nullable=False)
    op.alter_column("budgets", "updated_at", nullable=False)
    op.alter_column("expense_splits", "created_at", nullable=False)
    op.alter_column("recent_friends", "last_used_at", nullable=False)
    op.alter_column("recent_friends", "use_count", nullable=False)


def downgrade() -> None:
    # 6. Revert NOT NULL on timestamps
    op.alter_column("recent_friends", "use_count", nullable=True)
    op.alter_column("recent_friends", "last_used_at", nullable=True)
    op.alter_column("expense_splits", "created_at", nullable=True)
    op.alter_column("budgets", "updated_at", nullable=True)
    op.alter_column("budgets", "created_at", nullable=True)
    op.alter_column("budget_history", "created_at", nullable=True)

    # 5. Drop CHECK constraints
    op.drop_constraint("ck_budgets_monthly_amount_positive", "budgets", type_="check")
    op.drop_constraint("ck_transactions_quantity_non_negative", "transactions", type_="check")
    op.drop_constraint("ck_transactions_health_score_range", "transactions", type_="check")

    # 4. Recreate duplicate index
    op.create_index("idx_budget_history_user_month", "budget_history", ["user_id", "month"])

    # 3. Drop FK on user_rate_limits
    op.drop_constraint("user_rate_limits_firebase_uid_fkey", "user_rate_limits", type_="foreignkey")

    # 2. Revert transactions.user_id to NO ACTION
    op.drop_constraint("transactions_user_id_fkey", "transactions", type_="foreignkey")
    op.create_foreign_key(
        "transactions_user_id_fkey", "transactions", "users",
        ["user_id"], ["id"]
    )

    # 1. Revert receipts.user_id to NO ACTION
    op.drop_constraint("receipts_user_id_fkey", "receipts", type_="foreignkey")
    op.create_foreign_key(
        "receipts_user_id_fkey", "receipts", "users",
        ["user_id"], ["id"]
    )

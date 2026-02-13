"""Create budgets and budget_history tables

Revision ID: 016_create_budget_tables
Revises: 015_drop_ai_tables
Create Date: 2026-02-12

Creates the budgets and budget_history tables that the budget
endpoints depend on. Uses IF NOT EXISTS since these tables may
already exist from a prior create_all() run.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '016_create_budget_tables'
down_revision: Union[str, None] = '015_drop_ai_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # budgets table
    op.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            id VARCHAR PRIMARY KEY,
            user_id VARCHAR NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            monthly_amount FLOAT NOT NULL,
            category_allocations JSONB,
            notifications_enabled BOOLEAN DEFAULT true,
            alert_thresholds JSONB,
            is_smart_budget BOOLEAN DEFAULT true,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_budgets_user_id ON budgets(user_id)")

    # budget_history table
    op.execute("""
        CREATE TABLE IF NOT EXISTS budget_history (
            id VARCHAR PRIMARY KEY,
            user_id VARCHAR NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            monthly_amount FLOAT NOT NULL,
            category_allocations JSONB,
            month VARCHAR(7) NOT NULL,
            was_smart_budget BOOLEAN NOT NULL,
            was_deleted BOOLEAN DEFAULT false,
            notifications_enabled BOOLEAN DEFAULT true,
            alert_thresholds JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            UNIQUE (user_id, month)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_budget_history_user_month ON budget_history(user_id, month)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS budget_history")
    op.execute("DROP TABLE IF EXISTS budgets")

"""Add server-side UUID defaults to budget table IDs

Revision ID: 017_fix_budget_id_defaults
Revises: 016_create_budget_tables
Create Date: 2026-02-12

The budget_history table was created via raw SQL without a server-side
default for the id column. The Python-side default (uuid4) only works
when SQLAlchemy created the table via create_all(). This adds
gen_random_uuid() as the server default so PostgreSQL generates UUIDs
automatically.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '017_fix_budget_id_defaults'
down_revision: Union[str, None] = '016_create_budget_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE budget_history ALTER COLUMN id SET DEFAULT gen_random_uuid()::text")
    op.execute("ALTER TABLE budgets ALTER COLUMN id SET DEFAULT gen_random_uuid()::text")


def downgrade() -> None:
    op.execute("ALTER TABLE budget_history ALTER COLUMN id DROP DEFAULT")
    op.execute("ALTER TABLE budgets ALTER COLUMN id DROP DEFAULT")

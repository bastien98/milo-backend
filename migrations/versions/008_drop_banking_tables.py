"""Drop banking tables - remove bank integration feature

Revision ID: 008_drop_banking_tables
Revises: 007_bank_receipt_matching
Create Date: 2026-02-05

Removes all banking-related tables (bank_connections, bank_accounts,
bank_transactions) as the bank integration feature has been removed.
The app is now focused purely on grocery receipt scanning.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "008_drop_banking_tables"
down_revision: Union[str, None] = "007_bank_receipt_matching"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop tables in reverse order (respecting foreign keys)
    op.execute("DROP TABLE IF EXISTS bank_transactions CASCADE")
    op.execute("DROP TABLE IF EXISTS bank_accounts CASCADE")
    op.execute("DROP TABLE IF EXISTS bank_connections CASCADE")


def downgrade() -> None:
    # Not restoring banking tables - feature permanently removed
    pass

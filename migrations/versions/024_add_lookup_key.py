"""Add lookup_key to transactions

Revision ID: 024_add_lookup_key
Revises: 023_drop_split_tables
Create Date: 2026-03-03

Adds a composite lookup_key column (normalized_name|pack_qty|pack_size|pack_unit)
for deterministic receipt-item → SKU mapping.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "024_add_lookup_key"
down_revision: str = "023_drop_split_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("lookup_key", sa.String(255), nullable=True))
    op.create_index("ix_transactions_lookup_key", "transactions", ["lookup_key"])

    # Backfill existing rows from normalized_name + dp_pack_* fields
    op.execute("""
        UPDATE transactions
        SET lookup_key = normalized_name || '|' ||
            COALESCE(dp_pack_quantity, 1)::text || '|' ||
            COALESCE(dp_pack_size::text, '') || '|' ||
            COALESCE(dp_pack_unit, '')
        WHERE normalized_name IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_index("ix_transactions_lookup_key", table_name="transactions")
    op.drop_column("transactions", "lookup_key")

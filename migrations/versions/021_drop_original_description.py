"""Drop original_description and dp_packaging_type from transactions

Revision ID: 021_drop_original_desc
Revises: 020_add_error_code
Create Date: 2026-02-27

item_name now stores the raw receipt text (what original_description had).
Existing rows: copy original_description -> item_name before dropping.
dp_packaging_type removed (poorly populated, not needed).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "021_drop_original_desc"
down_revision: Union[str, None] = "020_add_error_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Copy original_description into item_name for existing rows
    op.execute(
        "UPDATE transactions SET item_name = original_description "
        "WHERE original_description IS NOT NULL"
    )
    op.drop_column("transactions", "original_description")
    op.drop_column("transactions", "dp_packaging_type")


def downgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("original_description", sa.Text(), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("dp_packaging_type", sa.String(10), nullable=True),
    )
    # Copy item_name back to original_description
    op.execute(
        "UPDATE transactions SET original_description = item_name"
    )

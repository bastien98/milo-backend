"""Rename 'Beer & Wine (Retail)' category to 'Alcohol'

Revision ID: 009_rename_alcohol_category
Revises: 008_drop_banking_tables
Create Date: 2026-02-08

Updates existing transactions to use the new broader category name.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "009_rename_alcohol_category"
down_revision: Union[str, None] = "008_drop_banking_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE transactions SET category = 'Alcohol' WHERE category = 'Beer & Wine (Retail)'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE transactions SET category = 'Beer & Wine (Retail)' WHERE category = 'Alcohol'"
    )

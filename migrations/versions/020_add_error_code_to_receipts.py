"""Add error_code column to receipts table

Revision ID: 020_add_error_code
Revises: 019_add_dp_fields
Create Date: 2026-02-27

Adds error_code column for structured error identification (e.g., 'unsupported_store').
Allows the frontend to display localized error messages based on the code.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "020_add_error_code"
down_revision: Union[str, None] = "019_add_dp_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "receipts",
        sa.Column("error_code", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("receipts", "error_code")

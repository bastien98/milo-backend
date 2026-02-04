"""Add matched_receipt_id to bank_transactions for receipt deduplication

Revision ID: 007_bank_receipt_matching
Revises: 006_category_enum_to_string
Create Date: 2026-02-04

Adds a matched_receipt_id column to the bank_transactions table so that
bank transactions can be linked to scanned receipts when a duplicate is
detected. The BankTransactionStatus enum gains a 'receipt_matched' value
(stored as VARCHAR string, no PostgreSQL enum alteration needed).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "007_bank_receipt_matching"
down_revision: Union[str, None] = "006_category_enum_to_string"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add matched_receipt_id column to bank_transactions
    op.add_column(
        "bank_transactions",
        sa.Column(
            "matched_receipt_id",
            sa.String(),
            sa.ForeignKey("receipts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Add index for efficient lookups by matched_receipt_id
    op.create_index(
        "ix_bank_transactions_matched_receipt_id",
        "bank_transactions",
        ["matched_receipt_id"],
    )


def downgrade() -> None:
    # Drop index first
    op.drop_index(
        "ix_bank_transactions_matched_receipt_id",
        table_name="bank_transactions",
    )

    # Drop column
    op.drop_column("bank_transactions", "matched_receipt_id")

"""Add fraud detection fields to receipts

Revision ID: 034_add_fraud_fields
Revises: 033_add_spins_available
Create Date: 2026-03-06
"""

from alembic import op
import sqlalchemy as sa

revision: str = "034_add_fraud_fields"
down_revision: str = "033_add_spins_available"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("receipts", sa.Column("receipt_fingerprint", sa.String(128), nullable=True))
    op.add_column("receipts", sa.Column("fraud_score", sa.Float(), nullable=True))
    op.add_column("receipts", sa.Column("fraud_flags", sa.Text(), nullable=True))
    op.create_index("ix_receipts_receipt_fingerprint", "receipts", ["receipt_fingerprint"])


def downgrade() -> None:
    op.drop_index("ix_receipts_receipt_fingerprint", table_name="receipts")
    op.drop_column("receipts", "fraud_flags")
    op.drop_column("receipts", "fraud_score")
    op.drop_column("receipts", "receipt_fingerprint")

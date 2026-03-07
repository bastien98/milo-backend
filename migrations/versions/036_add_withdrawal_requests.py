"""Add withdrawal_requests table and IBAN fields to user_profiles

Revision ID: 036_add_withdrawal_requests
Revises: 035_add_referral_claim_columns
Create Date: 2026-03-07
"""

from alembic import op
import sqlalchemy as sa

revision: str = "036_add_withdrawal_requests"
down_revision: str = "035_add_referral_claim_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum and table via raw SQL to avoid asyncpg create_type conflicts
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE withdrawalstatus AS ENUM "
        "('pending_review', 'auto_approved', 'approved', 'rejected', 'paid_out'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )

    op.execute("""
        CREATE TABLE withdrawal_requests (
            id VARCHAR NOT NULL PRIMARY KEY,
            user_id VARCHAR NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            amount FLOAT NOT NULL,
            iban VARCHAR NOT NULL,
            iban_last4 VARCHAR(4) NOT NULL,
            status withdrawalstatus NOT NULL DEFAULT 'pending_review',
            fraud_check_passed BOOLEAN NOT NULL DEFAULT false,
            fraud_check_details JSONB,
            admin_notes VARCHAR,
            reviewed_at TIMESTAMP WITH TIME ZONE,
            paid_out_at TIMESTAMP WITH TIME ZONE,
            wise_transfer_id VARCHAR,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    op.create_index("ix_withdrawal_requests_user_id", "withdrawal_requests", ["user_id"])
    op.create_index("ix_withdrawal_requests_status", "withdrawal_requests", ["status"])

    # Add IBAN fields to user_profiles
    op.add_column("user_profiles", sa.Column("iban", sa.String(), nullable=True))
    op.add_column("user_profiles", sa.Column("iban_last4", sa.String(4), nullable=True))


def downgrade() -> None:
    op.drop_column("user_profiles", "iban_last4")
    op.drop_column("user_profiles", "iban")
    op.drop_index("ix_withdrawal_requests_status", table_name="withdrawal_requests")
    op.drop_index("ix_withdrawal_requests_user_id", table_name="withdrawal_requests")
    op.drop_table("withdrawal_requests")
    op.execute("DROP TYPE IF EXISTS withdrawalstatus")

"""Initial banking tables migration

Revision ID: 001_initial_banking
Revises:
Create Date: 2025-02-01

This migration creates the EnableBanking integration tables.
Uses IF NOT EXISTS to be safe for existing deployments.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_initial_banking'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create bank_connections table
    op.execute("""
        CREATE TABLE IF NOT EXISTS bank_connections (
            id VARCHAR PRIMARY KEY,
            user_id VARCHAR NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            session_id VARCHAR UNIQUE,
            aspsp_name VARCHAR NOT NULL,
            aspsp_country VARCHAR(2) NOT NULL,
            auth_state VARCHAR,
            callback_type VARCHAR DEFAULT 'web' NOT NULL,
            status VARCHAR DEFAULT 'pending' NOT NULL,
            valid_until TIMESTAMP WITH TIME ZONE,
            error_message TEXT,
            raw_response JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)

    # Create indexes for bank_connections
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_bank_connections_user_id
        ON bank_connections(user_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_bank_connections_auth_state
        ON bank_connections(auth_state)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_bank_connections_user_status
        ON bank_connections(user_id, status)
    """)

    # Create bank_accounts table
    op.execute("""
        CREATE TABLE IF NOT EXISTS bank_accounts (
            id VARCHAR PRIMARY KEY,
            connection_id VARCHAR NOT NULL REFERENCES bank_connections(id) ON DELETE CASCADE,
            account_uid VARCHAR NOT NULL,
            resource_id VARCHAR,
            iban VARCHAR,
            account_name VARCHAR,
            holder_name VARCHAR,
            currency VARCHAR(3) DEFAULT 'EUR',
            balance FLOAT,
            balance_type VARCHAR,
            is_active BOOLEAN DEFAULT true,
            last_synced_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)

    # Create indexes for bank_accounts
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_bank_accounts_connection_id
        ON bank_accounts(connection_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_bank_accounts_iban
        ON bank_accounts(iban)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_bank_accounts_connection_uid
        ON bank_accounts(connection_id, account_uid)
    """)

    # Create bank_transactions table
    op.execute("""
        CREATE TABLE IF NOT EXISTS bank_transactions (
            id VARCHAR PRIMARY KEY,
            account_id VARCHAR NOT NULL REFERENCES bank_accounts(id) ON DELETE CASCADE,
            transaction_id VARCHAR NOT NULL,
            entry_reference VARCHAR,
            amount FLOAT NOT NULL,
            currency VARCHAR(3) DEFAULT 'EUR',
            creditor_name VARCHAR,
            creditor_iban VARCHAR,
            debtor_name VARCHAR,
            debtor_iban VARCHAR,
            booking_date DATE NOT NULL,
            value_date DATE,
            description TEXT,
            remittance_info TEXT,
            status VARCHAR DEFAULT 'pending' NOT NULL,
            imported_transaction_id VARCHAR REFERENCES transactions(id) ON DELETE SET NULL,
            suggested_category VARCHAR,
            category_confidence FLOAT,
            raw_response JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)

    # Create indexes for bank_transactions
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_bank_transactions_account_id
        ON bank_transactions(account_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_bank_transactions_booking_date
        ON bank_transactions(account_id, booking_date)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_bank_transactions_status
        ON bank_transactions(status)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_bank_transactions_account_txn
        ON bank_transactions(account_id, transaction_id)
    """)


def downgrade() -> None:
    # Drop tables in reverse order (respecting foreign keys)
    op.execute("DROP TABLE IF EXISTS bank_transactions CASCADE")
    op.execute("DROP TABLE IF EXISTS bank_accounts CASCADE")
    op.execute("DROP TABLE IF EXISTS bank_connections CASCADE")

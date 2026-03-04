"""Add cashback_transactions and cashback_balances tables.

Revision ID: 027_add_cashback_tables
Revises: 026_merge_heads
Create Date: 2026-03-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "027_add_cashback_tables"
down_revision: str = "026_merge_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum type
    cashbackstatus = sa.Enum("pending", "confirmed", "paid_out", name="cashbackstatus")
    cashbackstatus.create(op.get_bind(), checkfirst=True)

    # cashback_transactions — one row per completed receipt
    op.create_table(
        "cashback_transactions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "receipt_id",
            sa.String(),
            sa.ForeignKey("receipts.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("receipt_total", sa.Float(), nullable=False),
        sa.Column("cashback_amount", sa.Float(), nullable=False),
        sa.Column("effective_rate", sa.Float(), nullable=False),
        sa.Column(
            "status",
            cashbackstatus,
            nullable=False,
            server_default="confirmed",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # cashback_balances — one row per user (running wallet balance)
    op.create_table(
        "cashback_balances",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("total_earned", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_paid_out", sa.Float(), nullable=False, server_default="0"),
        sa.Column("current_balance", sa.Float(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("cashback_balances")
    op.drop_table("cashback_transactions")
    sa.Enum(name="cashbackstatus").drop(op.get_bind(), checkfirst=True)

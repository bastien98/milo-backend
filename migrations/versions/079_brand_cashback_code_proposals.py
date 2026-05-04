"""brand cashback: admin-reviewed queue for code-extension proposals

Revision ID: 079_brand_cashback_code_proposals
Revises: 078_transaction_article_codes_list
Create Date: 2026-05-04

When the matcher's Tier 2 (text-exact) match fires for a code-mode line item
and the receipt brought codes that aren't yet on the line item, today the
matcher silently appends them to product_codes — which globally pollutes the
allow-list if the text match was a fluke (right text, wrong product code).

This migration introduces an admin-review queue. The matcher proposes new
codes; admins approve or reject. Approved proposals are merged into the line
item's product_codes by the existing add_product_codes path.

Schema:
- one row per (line_item_id, code) — UNIQUE constraint makes proposals
  idempotent. If 50 users hit the same fluke code, only one proposal exists.
- source attribution on the first proposer (user_id + receipt_id) for audit
- status: pending | approved | rejected; reviewer + timestamp on transition
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "079_brand_cashback_code_proposals"
down_revision: Union[str, None] = "078_transaction_article_codes_list"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brand_cashback_code_proposals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "line_item_id",
            sa.String(),
            sa.ForeignKey("brand_cashback_store_line_items.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column(
            "source_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_receipt_id",
            sa.String(),
            sa.ForeignKey("receipts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "proposed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reviewed_by",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "line_item_id", "code", name="uq_code_proposals_line_item_code"
        ),
    )
    op.create_index(
        "ix_code_proposals_status_proposed",
        "brand_cashback_code_proposals",
        ["status", sa.text("proposed_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_code_proposals_status_proposed",
        table_name="brand_cashback_code_proposals",
    )
    op.drop_table("brand_cashback_code_proposals")

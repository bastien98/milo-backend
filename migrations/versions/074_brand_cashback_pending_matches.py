"""brand cashback: pending-review queue for near-miss receipts

Revision ID: 074_brand_cashback_pending_matches
Revises: 073_brand_cashback_split_claims_earnings
Create Date: 2026-05-03

Holds receipts that fuzzily matched a campaign the user has claimed but did
not pass strict equality. Admin reviews the row; on approve we create a
brand_cashback_earnings row and (optionally) extend the matched line item's
alt_line_items so future receipts with the same string award instantly.

UNIQUE (user_id, campaign_id, receipt_id) makes queue insertion idempotent
if the receipt background worker re-runs.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "074_brand_cashback_pending_matches"
down_revision: Union[str, None] = "073_brand_cashback_split_claims_earnings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brand_cashback_pending_matches",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            sa.String(),
            sa.ForeignKey("brand_cashback_campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "receipt_id",
            sa.String(),
            sa.ForeignKey("receipts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("candidate_string", sa.Text(), nullable=False),
        sa.Column(
            "matched_line_item_id",
            sa.String(),
            sa.ForeignKey("brand_cashback_store_line_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("match_score", sa.Float(), nullable=False),
        sa.Column("store_name", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reviewed_by",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("denial_reason", sa.Text(), nullable=True),
        sa.Column(
            "earning_id",
            sa.String(),
            sa.ForeignKey("brand_cashback_earnings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "user_id",
            "campaign_id",
            "receipt_id",
            name="uq_brand_cashback_pending_user_campaign_receipt",
        ),
    )
    op.create_index(
        "ix_bcpm_status_created",
        "brand_cashback_pending_matches",
        ["status", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_bcpm_user",
        "brand_cashback_pending_matches",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_bcpm_user", table_name="brand_cashback_pending_matches")
    op.drop_index("ix_bcpm_status_created", table_name="brand_cashback_pending_matches")
    op.drop_table("brand_cashback_pending_matches")

"""brand cashback: split intent (claims) from match events (earnings); drop claim window

Revision ID: 073_brand_cashback_split_claims_earnings
Revises: 072_brand_cashback_image_thumb_key
Create Date: 2026-05-03

Replaces the time-bounded claim-window flow with claim-then-match:
  - A claim is now persistent intent: at most one row per (user, campaign).
  - Each successful receipt match creates an earnings row (multiple per
    (user, campaign) up to max_redemptions_per_user).
  - Validity collapses to: campaign not expired AND caps not exhausted.

Schema changes
--------------
1. Create brand_cashback_claims (new table): intent only.
2. Backfill from user_brand_cashback_claims, deduping by (user_id, campaign_id)
   using the earliest claimed_at.
3. Drop the now-redundant 'claimed' rows from user_brand_cashback_claims.
4. Drop the status column.
5. Rename user_brand_cashback_claims -> brand_cashback_earnings.
6. Tighten earnings columns to NOT NULL (every row is now a real match).
7. Drop claim_window_days from brand_cashback_campaigns.

Down migration restores the previous shape on a best-effort basis: every
earnings row reappears with status='earned', and every claim row reappears
with status='claimed' (NULL receipt_id/etc). Acceptable for non-prod;
prod restore should be reviewed manually.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "073_brand_cashback_split_claims_earnings"
down_revision: Union[str, None] = "072_brand_cashback_image_thumb_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. New persistent-intent table.
    op.create_table(
        "brand_cashback_claims",
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
            "claimed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", "campaign_id", name="uq_brand_cashback_claims_user_campaign"),
    )
    op.create_index(
        "ix_brand_cashback_claims_user_id",
        "brand_cashback_claims",
        ["user_id"],
    )
    op.create_index(
        "ix_brand_cashback_claims_campaign_id",
        "brand_cashback_claims",
        ["campaign_id"],
    )

    # 2. Backfill: one claim row per (user, campaign), earliest claimed_at wins.
    op.execute(
        """
        INSERT INTO brand_cashback_claims (id, user_id, campaign_id, claimed_at)
        SELECT
            gen_random_uuid()::text,
            user_id,
            campaign_id,
            MIN(claimed_at)
        FROM user_brand_cashback_claims
        GROUP BY user_id, campaign_id
        """
    )

    # 3. Drop intent-only rows; what remains is one row per match event.
    op.execute("DELETE FROM user_brand_cashback_claims WHERE status = 'claimed'")

    # 4. The status column is now constant ('earned') — drop it.
    op.drop_column("user_brand_cashback_claims", "status")

    # 5. Rename to reflect the new meaning.
    op.rename_table("user_brand_cashback_claims", "brand_cashback_earnings")

    # 6. The intent timestamp now lives on brand_cashback_claims.
    op.drop_column("brand_cashback_earnings", "claimed_at")

    # 7. All earnings rows are real matches; tighten the schema to match.
    op.alter_column("brand_cashback_earnings", "receipt_id", nullable=False)
    op.alter_column("brand_cashback_earnings", "matched_line_item_id", nullable=False)
    op.alter_column("brand_cashback_earnings", "cashback_earned_cents", nullable=False)
    op.alter_column("brand_cashback_earnings", "earned_at", nullable=False)

    # 8. claim_window_days has no meaning in the new flow.
    op.drop_column("brand_cashback_campaigns", "claim_window_days")


def downgrade() -> None:
    # Reintroduce the column with the original default.
    op.add_column(
        "brand_cashback_campaigns",
        sa.Column(
            "claim_window_days",
            sa.Integer(),
            nullable=False,
            server_default="14",
        ),
    )

    # Loosen earnings columns again so we can re-insert intent-only rows.
    op.alter_column("brand_cashback_earnings", "earned_at", nullable=True)
    op.alter_column("brand_cashback_earnings", "cashback_earned_cents", nullable=True)
    op.alter_column("brand_cashback_earnings", "matched_line_item_id", nullable=True)
    op.alter_column("brand_cashback_earnings", "receipt_id", nullable=True)

    # Restore the claimed_at column that the old shape kept on every row.
    op.add_column(
        "brand_cashback_earnings",
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Backfill from earned_at where we have it, so existing rows don't all
    # get the migration timestamp.
    op.execute(
        "UPDATE brand_cashback_earnings SET claimed_at = COALESCE(earned_at, claimed_at)"
    )

    op.rename_table("brand_cashback_earnings", "user_brand_cashback_claims")

    op.add_column(
        "user_brand_cashback_claims",
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="earned",
        ),
    )

    # Reconstruct intent-only ('claimed') rows from the new claims table.
    op.execute(
        """
        INSERT INTO user_brand_cashback_claims (
            id, user_id, campaign_id, claimed_at, status
        )
        SELECT id, user_id, campaign_id, claimed_at, 'claimed'
        FROM brand_cashback_claims
        """
    )

    op.drop_index("ix_brand_cashback_claims_campaign_id", table_name="brand_cashback_claims")
    op.drop_index("ix_brand_cashback_claims_user_id", table_name="brand_cashback_claims")
    op.drop_table("brand_cashback_claims")

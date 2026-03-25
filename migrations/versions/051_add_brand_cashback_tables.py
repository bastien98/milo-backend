"""Add brand cashback tables

Revision ID: 051_add_brand_cashback_tables
Revises: 050_rename_promo_weekly_candidates
Create Date: 2026-03-25

Changes:
- Create brand_cashback_campaigns table
- Create brand_cashback_store_line_items table
- Create user_brand_cashback_claims table with unique constraint (user_id, campaign_id)
"""

revision = "051_add_brand_cashback_tables"
down_revision = "050_rename_promo_weekly_candidates"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op


def upgrade() -> None:
    op.create_table(
        "brand_cashback_campaigns",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("brand_name", sa.String(), nullable=False),
        sa.Column("product_name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("cashback_amount_cents", sa.Integer(), nullable=False),
        sa.Column("image_system_name", sa.String(), nullable=False, server_default="tag.fill"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eligible_stores", JSONB(), nullable=False, server_default="[]"),
        sa.Column("requires_store", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "brand_cashback_store_line_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("campaign_id", sa.String(), nullable=False),
        sa.Column("store_name", sa.String(), nullable=False),
        sa.Column("exact_line_item", sa.String(), nullable=False),
        sa.Column("alt_line_items", JSONB(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["campaign_id"], ["brand_cashback_campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_brand_cashback_store_line_items_campaign_id",
        "brand_cashback_store_line_items",
        ["campaign_id"],
    )
    op.create_index(
        "ix_brand_cashback_store_line_items_campaign_store",
        "brand_cashback_store_line_items",
        ["campaign_id", "store_name"],
    )

    op.create_table(
        "user_brand_cashback_claims",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("campaign_id", sa.String(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("status", sa.String(), nullable=False, server_default="claimed"),
        sa.Column("receipt_id", sa.String(), nullable=True),
        sa.Column("matched_line_item_id", sa.String(), nullable=True),
        sa.Column("cashback_earned_cents", sa.Integer(), nullable=True),
        sa.Column("earned_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["brand_cashback_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["receipt_id"], ["receipts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["matched_line_item_id"],
            ["brand_cashback_store_line_items.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "campaign_id", name="uq_user_campaign_claim"),
    )
    op.create_index(
        "ix_user_brand_cashback_claims_user_id",
        "user_brand_cashback_claims",
        ["user_id"],
    )
    op.create_index(
        "ix_user_brand_cashback_claims_campaign_id",
        "user_brand_cashback_claims",
        ["campaign_id"],
    )


def downgrade() -> None:
    op.drop_table("user_brand_cashback_claims")
    op.drop_table("brand_cashback_store_line_items")
    op.drop_table("brand_cashback_campaigns")

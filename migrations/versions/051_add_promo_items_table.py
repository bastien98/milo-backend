"""Add promo_items table for PostgreSQL-based promo storage

Revision ID: 051_add_promo_items_table
Revises: 050_rename_promo_weekly_candidates
Create Date: 2026-03-26

Changes:
- Create promo_items table to store extracted promo folder items
- Add B-tree indexes on source_retailer, granular_category, validity dates
"""

from alembic import op
import sqlalchemy as sa

revision = "051_add_promo_items_table"
down_revision = "050_rename_promo_weekly_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promo_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("display_name_lower", sa.String(), nullable=False),
        sa.Column("display_mechanism", sa.String(), nullable=False),
        sa.Column("display_description", sa.Text(), nullable=False, server_default=""),
        sa.Column("display_savings_label", sa.String(), nullable=False, server_default=""),
        sa.Column("display_unit_price", sa.String(), nullable=True),
        sa.Column("original_price", sa.Float(), nullable=False),
        sa.Column("promo_price", sa.Float(), nullable=False),
        sa.Column("savings_amount", sa.Float(), nullable=False),
        sa.Column("min_purchase_qty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("promo_depth", sa.Float(), nullable=False, server_default="0"),
        sa.Column("granular_category", sa.String(100), nullable=False),
        sa.Column("source_retailer", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False, server_default="folder"),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("promo_folder_url", sa.Text(), nullable=True),
        sa.Column("validity_start", sa.Date(), nullable=False),
        sa.Column("validity_end", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_promo_items_source_retailer", "promo_items", ["source_retailer"])
    op.create_index("ix_promo_items_granular_category", "promo_items", ["granular_category"])
    op.create_index("ix_promo_items_validity", "promo_items", ["validity_start", "validity_end"])


def downgrade() -> None:
    op.drop_index("ix_promo_items_validity", table_name="promo_items")
    op.drop_index("ix_promo_items_granular_category", table_name="promo_items")
    op.drop_index("ix_promo_items_source_retailer", table_name="promo_items")
    op.drop_table("promo_items")

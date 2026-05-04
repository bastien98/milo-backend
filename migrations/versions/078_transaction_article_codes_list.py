"""transactions: store ALL article/PLU/EAN codes per line as a JSONB array

Revision ID: 078_transaction_article_codes_list
Revises: 077_brand_cashback_line_item_codes
Create Date: 2026-05-04

The Gemini OCR pipeline now emits every digit-only code printed for a line
item (Delhaize sometimes prints both a short internal article number and the
12–13 digit manufacturer EAN). Storing them all on the transaction lets the
brand-cashback matcher do an any-of-any check against campaign product_codes,
without forcing the OCR layer to guess which code the admin typed.

Additive change:
  - new column dp_article_codes JSONB NOT NULL DEFAULT '[]'
  - backfill from existing dp_article_code (1-element array, or [] if null)
  - GIN index on dp_article_codes for fast containment queries
  - dp_article_code stays as the canonical longest-code singleton
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "078_transaction_article_codes_list"
down_revision: Union[str, None] = "077_brand_cashback_line_item_codes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column(
            "dp_article_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    # Backfill: every existing row with a non-null singleton becomes a 1-element list.
    op.execute(
        "UPDATE transactions "
        "SET dp_article_codes = jsonb_build_array(dp_article_code) "
        "WHERE dp_article_code IS NOT NULL AND dp_article_code <> ''"
    )
    op.create_index(
        "ix_transactions_dp_article_codes",
        "transactions",
        ["dp_article_codes"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_dp_article_codes", table_name="transactions")
    op.drop_column("transactions", "dp_article_codes")

"""add promo_text_markdown to promo_items

Revision ID: 064_add_promo_text_markdown
Revises: 063_promo_canonical_mechanism
Create Date: 2026-04-20

Adds a nullable TEXT column storing the verbatim promo tile text
reformatted as Markdown by Gemini. Rendered in the iOS detail sheet.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "064_add_promo_text_markdown"
down_revision: Union[str, None] = "063_promo_canonical_mechanism"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("promo_items", sa.Column("promo_text_markdown", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("promo_items", "promo_text_markdown")

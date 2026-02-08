"""Create user_enriched_profiles table

Revision ID: 005_enriched_profiles
Revises: 004_add_brand_premium
Create Date: 2026-02-03

One-to-one table with users storing aggregated shopping habits
and promo interest items as JSONB for LLM consumption.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = '005_enriched_profiles'
down_revision: Union[str, None] = '004_add_brand_premium'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_enriched_profiles',
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('shopping_habits', JSONB, nullable=True),
        sa.Column('promo_interest_items', JSONB, nullable=True),
        sa.Column('data_period_start', sa.Date(), nullable=True),
        sa.Column('data_period_end', sa.Date(), nullable=True),
        sa.Column('receipts_analyzed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_rebuilt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('user_enriched_profiles')

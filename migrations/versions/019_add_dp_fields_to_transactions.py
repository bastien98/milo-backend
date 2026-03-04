"""Add data platform (dp_) fields to transactions table

Revision ID: 019_add_dp_fields
Revises: 018_fix_constraints
Create Date: 2026-02-24

Adds 8 dp_ prefixed columns for data platform EAN matching and Pinecone vector search:
- dp_expanded_description: full product text for vector search embedding
- dp_pack_quantity: multi-pack count (e.g., 6 from 6x33cl)
- dp_pack_size: total pack size in ml or g (matches Daltix convention)
- dp_pack_unit: "ml" or "g"
- dp_packaging_type: blik/pet/fles/doos/brik/glas/zak
- dp_product_variant: flavor/style/sub-type
- dp_article_code: article/PLU code from receipt
- dp_is_bio: organic product flag
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '019_add_dp_fields'
down_revision: Union[str, None] = '018_fix_constraints'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('transactions', sa.Column('dp_expanded_description', sa.Text(), nullable=True))
    op.add_column('transactions', sa.Column('dp_pack_quantity', sa.Integer(), nullable=True))
    op.add_column('transactions', sa.Column('dp_pack_size', sa.Float(), nullable=True))
    op.add_column('transactions', sa.Column('dp_pack_unit', sa.String(5), nullable=True))
    op.add_column('transactions', sa.Column('dp_packaging_type', sa.String(10), nullable=True))
    op.add_column('transactions', sa.Column('dp_product_variant', sa.String(100), nullable=True))
    op.add_column('transactions', sa.Column('dp_article_code', sa.String(50), nullable=True))
    op.add_column('transactions', sa.Column('dp_is_bio', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    op.drop_column('transactions', 'dp_is_bio')
    op.drop_column('transactions', 'dp_article_code')
    op.drop_column('transactions', 'dp_product_variant')
    op.drop_column('transactions', 'dp_packaging_type')
    op.drop_column('transactions', 'dp_pack_unit')
    op.drop_column('transactions', 'dp_pack_size')
    op.drop_column('transactions', 'dp_pack_quantity')
    op.drop_column('transactions', 'dp_expanded_description')

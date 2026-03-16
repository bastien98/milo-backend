"""Add dp_packaging_type to transactions

Revision ID: 044_add_dp_packaging_type
Revises: 043_add_post_url
Create Date: 2026-03-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "044_add_dp_packaging_type"
down_revision: str = "043_add_post_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("dp_packaging_type", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("transactions", "dp_packaging_type")

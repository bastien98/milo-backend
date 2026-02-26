"""Add preferred_stores column to user_profiles

Revision ID: 019_add_preferred_stores
Revises: 018_add_nickname_age_language
Create Date: 2026-02-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "019_add_preferred_stores"
down_revision: str = "018_add_nickname_age_language"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("preferred_stores", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("user_profiles", "preferred_stores")

"""Add nickname, age, language columns to user_profiles

Revision ID: 018_add_nickname_age_language
Revises: 017_fix_budget_id_defaults
Create Date: 2026-02-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "018_add_nickname_age_language"
down_revision: str = "017_fix_budget_id_defaults"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("nickname", sa.String(), nullable=True))
    op.add_column("user_profiles", sa.Column("age", sa.Integer(), nullable=True))
    op.add_column("user_profiles", sa.Column("language", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_profiles", "language")
    op.drop_column("user_profiles", "age")
    op.drop_column("user_profiles", "nickname")

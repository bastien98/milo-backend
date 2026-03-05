"""Drop health_score and original_description columns from transactions.

Revision ID: 029_drop_health_score_and_original_description
Revises: 028_drop_user_rate_limits
Create Date: 2026-03-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "029_drop_health_score_and_original_description"
down_revision: str = "028_drop_user_rate_limits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS health_score")
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS original_description")


def downgrade() -> None:
    op.add_column("transactions", sa.Column("health_score", sa.Float(), nullable=True))
    op.add_column("transactions", sa.Column("original_description", sa.Text(), nullable=True))

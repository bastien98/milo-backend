"""Merge fraud detection and streak rewards branches

Revision ID: bc0e8e7940f4
Revises: 034_add_fraud_fields, 037_add_streak_rewards
Create Date: 2026-03-10 16:12:18.646026

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bc0e8e7940f4'
down_revision: Union[str, None] = ('034_add_fraud_fields', '037_add_streak_rewards')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

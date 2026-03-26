"""merge_parallel_branches

Revision ID: 054_merge_parallel_branches
Revises: 053_add_charity_donations, 053_drop_promo_interest_items
Create Date: 2026-03-26 22:38:03.832759

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '054_merge_parallel_branches'
down_revision: Union[str, None] = ('053_add_charity_donations', '053_drop_promo_interest_items')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

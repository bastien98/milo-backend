"""merge_heads

Revision ID: 8581df09ffe7
Revises: 054_merge_parallel_branches, 055_add_charity_rejected_status
Create Date: 2026-03-27 18:38:53.751283

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '056_merge_heads'
down_revision: Union[str, None] = ('054_merge_parallel_branches', '055_add_charity_rejected_status')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

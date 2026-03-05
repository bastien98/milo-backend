"""merge 030 heads

Revision ID: 031_merge_heads
Revises: 030_update_lookup_key_with_variant_bio, 030_add_spin_tables
Create Date: 2026-03-06
"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "031_merge_heads"
down_revision: tuple = (
    "030_update_lookup_key_with_variant_bio",
    "030_add_spin_tables",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

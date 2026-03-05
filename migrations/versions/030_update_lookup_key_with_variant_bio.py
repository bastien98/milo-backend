"""Update lookup_key to include variant and bio fields

Revision ID: 030_update_lookup_key_with_variant_bio
Revises: 029_drop_health_score_and_original_description
Create Date: 2026-03-05

Updates lookup_key format from normalized_name|pack_qty|pack_size|pack_unit
to normalized_name|pack_qty|pack_size|pack_unit|variant|is_bio
"""
from typing import Sequence, Union

from alembic import op

revision: str = "030_update_lookup_key_with_variant_bio"
down_revision: str = "029_drop_health_score_and_original_description"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE transactions
        SET lookup_key = normalized_name || '|' ||
            COALESCE(dp_pack_quantity, 1)::text || '|' ||
            COALESCE(dp_pack_size::text, '') || '|' ||
            COALESCE(dp_pack_unit, '') || '|' ||
            COALESCE(dp_product_variant, '') || '|' ||
            CASE WHEN dp_is_bio THEN 'bio' ELSE '' END
        WHERE normalized_name IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE transactions
        SET lookup_key = normalized_name || '|' ||
            COALESCE(dp_pack_quantity, 1)::text || '|' ||
            COALESCE(dp_pack_size::text, '') || '|' ||
            COALESCE(dp_pack_unit, '')
        WHERE normalized_name IS NOT NULL
    """)

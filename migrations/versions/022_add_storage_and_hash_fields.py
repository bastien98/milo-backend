"""Add storage_key and content_hash to receipts

Revision ID: 022_add_storage_hash
Revises: 021_drop_original_desc
Create Date: 2026-02-27

Adds storage_key for S3 object references and content_hash (SHA-256)
for global duplicate detection across all users.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "022_add_storage_hash"
down_revision: Union[str, None] = "021_drop_original_desc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "receipts",
        sa.Column("storage_key", sa.String(), nullable=True),
    )
    op.add_column(
        "receipts",
        sa.Column("content_hash", sa.String(64), nullable=True),
    )
    # Unique partial index: enforce uniqueness on content_hash for non-failed receipts.
    # This prevents the race condition where two concurrent uploads with the same hash
    # both pass the application-level duplicate check before either commits.
    # FAILED receipts are excluded so users can retry failed uploads.
    op.execute(
        "CREATE UNIQUE INDEX ix_receipts_content_hash_active "
        "ON receipts (content_hash) "
        "WHERE content_hash IS NOT NULL AND status != 'FAILED'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_receipts_content_hash_active")
    op.drop_column("receipts", "content_hash")
    op.drop_column("receipts", "storage_key")

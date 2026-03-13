"""Add proof_image_key and proof_status to lottery_entries

Revision ID: 041_add_lottery_proof_image
Revises: 040_add_lottery_system
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa

revision: str = "041_add_lottery_proof_image"
down_revision: str = "040_add_lottery_system"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lottery_entries", sa.Column("proof_image_key", sa.String(), nullable=True))
    op.add_column("lottery_entries", sa.Column("proof_status", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("lottery_entries", "proof_status")
    op.drop_column("lottery_entries", "proof_image_key")

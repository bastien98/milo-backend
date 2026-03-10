"""Add geo data and itsme identity fields to user_profiles

Revision ID: 039_add_geo_and_itsme_fields
Revises: 038_add_household_number
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa

revision: str = "039_add_geo_and_itsme_fields"
down_revision: str = "038_add_household_number"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("street_address", sa.String(), nullable=True))
    op.add_column("user_profiles", sa.Column("postal_code", sa.String(20), nullable=True))
    op.add_column("user_profiles", sa.Column("city", sa.String(), nullable=True))
    op.add_column("user_profiles", sa.Column("country", sa.String(), nullable=True))
    op.add_column("user_profiles", sa.Column("itsme_sub", sa.String(), nullable=True))
    op.create_index(op.f("ix_user_profiles_itsme_sub"), "user_profiles", ["itsme_sub"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_profiles_itsme_sub"), table_name="user_profiles")
    op.drop_column("user_profiles", "itsme_sub")
    op.drop_column("user_profiles", "country")
    op.drop_column("user_profiles", "city")
    op.drop_column("user_profiles", "postal_code")
    op.drop_column("user_profiles", "street_address")

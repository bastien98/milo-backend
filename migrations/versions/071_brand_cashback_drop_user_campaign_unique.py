"""brand cashback: drop unique(user_id, campaign_id) so max_redemptions_per_user can exceed 1

Revision ID: 071_brand_cashback_drop_user_campaign_unique
Revises: 070_brand_cashback_coupon_fields
Create Date: 2026-05-03

The unique constraint on user_brand_cashback_claims hard-capped to 1 claim
per (user, campaign), making the new max_redemptions_per_user field
unenforceable above 1. Drop it; enforcement now happens in the service
layer via a count check before insert.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "071_brand_cashback_drop_user_campaign_unique"
down_revision: Union[str, None] = "070_brand_cashback_coupon_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_user_campaign_claim",
        "user_brand_cashback_claims",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_user_campaign_claim",
        "user_brand_cashback_claims",
        ["user_id", "campaign_id"],
    )

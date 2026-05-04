"""drop legacy gamification tables and enum types

Revision ID: 076_drop_legacy_gamification
Revises: 075_create_brand_cashback_balance
Create Date: 2026-05-03

The app pivoted to brand-cashback-only — receipts no longer earn points,
spins, streaks, lottery tickets, referral bonuses, or charity credit. The
withdrawal flow now debits BrandCashbackBalance directly. Everything below
becomes dead schema and gets dropped:

  - cashback_transactions / cashback_balances (legacy points ledger)
  - spin_transactions / spin_budget (spin wheel)
  - streak_rewards (weekly streaks)
  - lottery_drawings / lottery_entries (monthly lottery)
  - referrals (referral program)
  - charity_donations (charity payout)

Plus the PG enum types that backed those tables. The downgrade path is
intentionally not implemented — once we drop the data this is a one-way trip.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "076_drop_legacy_gamification"
down_revision: Union[str, None] = "075_create_brand_cashback_balance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tables dropped in dependency order (children before parents — though here
# every table FKs to users, so ordering is mostly cosmetic).
LEGACY_TABLES = [
    "lottery_entries",
    "lottery_drawings",
    "streak_rewards",
    "spin_transactions",
    "spin_budget",
    "referrals",
    "charity_donations",
    "cashback_transactions",
    "cashback_balances",
]

# PostgreSQL enum types created by the SQLAlchemy SAEnum bindings on those
# tables. Drop AFTER tables since columns reference them.
LEGACY_ENUM_TYPES = [
    "cashbackstatus",
    "referralstatus",
    "charitydonationstatus",
    "streakrewardstatus",
    "streakrewardtype",
    "tierlevel",
    "spintype",
    "lotterydrawingstatus",
]


def upgrade() -> None:
    for table in LEGACY_TABLES:
        op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    for enum_name in LEGACY_ENUM_TYPES:
        op.execute(f'DROP TYPE IF EXISTS "{enum_name}"')


def downgrade() -> None:
    raise NotImplementedError(
        "Migration 076 is one-way. The gamification schema and code are gone — "
        "restoring would require recreating models that no longer exist in this repo."
    )

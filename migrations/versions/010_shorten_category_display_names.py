"""Shorten category display names for cleaner UI

Revision ID: 010_shorten_categories
Revises: 009_rename_alcohol_category
Create Date: 2026-02-08

Renames verbose sub-category names to short, clean display names.
Updates both transactions.category and budgets.category_allocations JSONB.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "010_shorten_categories"
down_revision: Union[str, None] = "009_rename_alcohol_category"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Old name -> New name mapping
RENAMES = [
    ("Fresh Produce (Fruit & Veg)", "Fresh Produce"),
    ("Meat Poultry & Seafood", "Meat & Seafood"),
    ("Dairy Cheese & Eggs", "Dairy & Eggs"),
    ("Bakery & Bread", "Bakery"),
    ("Pantry Staples (Pasta/Rice/Oil)", "Pantry"),
    ("Frozen Foods", "Frozen"),
    ("Ready Meals & Prepared Food", "Ready Meals"),
    ("Snacks & Candy", "Snacks"),
    ("Beverages (Non-Alcoholic)", "Drinks"),
    ("Household Consumables (Paper/Cleaning)", "Household"),
    ("Personal Hygiene (Soap/Shampoo)", "Personal Care"),
    ("Baby Food & Formula", "Baby & Kids"),
    ("Pet Food & Supplies", "Pet Supplies"),
    ("Tobacco Products", "Tobacco"),
]


def upgrade() -> None:
    # Rename in transactions table
    for old_name, new_name in RENAMES:
        op.execute(
            f"UPDATE transactions SET category = '{new_name}' WHERE category = '{old_name}'"
        )

    # Rename in budgets.category_allocations JSONB
    # Each allocation is: {"category": "...", "amount": ..., "is_locked": ...}
    for old_name, new_name in RENAMES:
        op.execute(f"""
            UPDATE budgets
            SET category_allocations = (
                SELECT jsonb_agg(
                    CASE
                        WHEN elem->>'category' = '{old_name}'
                        THEN jsonb_set(elem, '{{category}}', '"{new_name}"'::jsonb)
                        ELSE elem
                    END
                )
                FROM jsonb_array_elements(category_allocations) AS elem
            )
            WHERE category_allocations IS NOT NULL
            AND category_allocations::text LIKE '%{old_name}%'
        """)


def downgrade() -> None:
    # Reverse: new name -> old name
    for old_name, new_name in RENAMES:
        op.execute(
            f"UPDATE transactions SET category = '{old_name}' WHERE category = '{new_name}'"
        )

    for old_name, new_name in RENAMES:
        op.execute(f"""
            UPDATE budgets
            SET category_allocations = (
                SELECT jsonb_agg(
                    CASE
                        WHEN elem->>'category' = '{new_name}'
                        THEN jsonb_set(elem, '{{category}}', '"{old_name}"'::jsonb)
                        ELSE elem
                    END
                )
                FROM jsonb_array_elements(category_allocations) AS elem
            )
            WHERE category_allocations IS NOT NULL
            AND category_allocations::text LIKE '%{new_name}%'
        """)

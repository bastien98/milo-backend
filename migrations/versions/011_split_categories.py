"""Split categories: Meat & Seafood, Fresh Produce; add Candy

Revision ID: 011_split_categories
Revises: 010_shorten_categories
Create Date: 2026-02-08

Splits combined categories into separate ones and adds Candy.
Existing "Fresh Produce" transactions default to "Vegetables".
Existing "Meat & Seafood" transactions default to "Meat".
New receipt scans will categorize into the correct split category.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "011_split_categories"
down_revision: Union[str, None] = "010_shorten_categories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Splits: old name -> default new name
SPLITS = [
    ("Fresh Produce", "Vegetables"),
    ("Meat & Seafood", "Meat"),
]


def upgrade() -> None:
    # Rename split categories in transactions
    for old_name, new_name in SPLITS:
        op.execute(
            f"UPDATE transactions SET category = '{new_name}' WHERE category = '{old_name}'"
        )

    # Rename split categories in budgets.category_allocations JSONB
    for old_name, new_name in SPLITS:
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
    # Merge back: new split names -> old combined name
    # Vegetables and Fruits -> Fresh Produce
    op.execute(
        "UPDATE transactions SET category = 'Fresh Produce' WHERE category IN ('Vegetables', 'Fruits')"
    )
    # Meat and Seafood -> Meat & Seafood
    op.execute(
        "UPDATE transactions SET category = 'Meat & Seafood' WHERE category IN ('Meat', 'Seafood')"
    )
    # Candy -> Snacks
    op.execute(
        "UPDATE transactions SET category = 'Snacks' WHERE category = 'Candy'"
    )

    # Budgets JSONB downgrade
    for new_names, old_name in [
        (["Vegetables", "Fruits"], "Fresh Produce"),
        (["Meat", "Seafood"], "Meat & Seafood"),
        (["Candy"], "Snacks"),
    ]:
        for new_name in new_names:
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

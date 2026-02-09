"""Cleanup all remaining old/variant category names

Revision ID: 013_cleanup_categories
Revises: 012_merge_branches
Create Date: 2026-02-09

Catches all remaining old category values in the database that were
not covered by previous migrations (AI-generated variants, old display
names, legacy names, etc.) and maps them to the current canonical names.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "013_cleanup_categories"
down_revision: Union[str, None] = "012_merge_branches"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Comprehensive mapping of all known old/variant names to current canonical names.
# Uses LIKE patterns for fuzzy matching.
# Format: (SQL WHERE condition, new canonical name)
CLEANUP_RULES = [
    # --- Fresh Food splits ---
    ("category ILIKE '%fruit%' AND category != 'Fruits'", "Fruits"),
    ("category ILIKE '%vegetable%' AND category != 'Vegetables'", "Vegetables"),
    ("category ILIKE '%produce%' AND category != 'Vegetables'", "Vegetables"),
    ("category ILIKE '%herb%' AND category NOT IN ('Fruits', 'Vegetables', 'Pantry')", "Vegetables"),

    # Old combined names
    ("category = 'Fresh Produce'", "Vegetables"),
    ("category = 'Meat & Seafood'", "Meat"),
    ("category ILIKE 'Meat Poultry%'", "Meat"),

    # Seafood variants
    ("category ILIKE '%seafood%' AND category != 'Seafood'", "Seafood"),
    ("category ILIKE '%fish%' AND category NOT IN ('Meat', 'Seafood')", "Seafood"),

    # Meat variants
    ("category ILIKE '%meat%' AND category NOT IN ('Meat', 'Seafood')", "Meat"),
    ("category ILIKE '%poultry%' AND category != 'Meat'", "Meat"),
    ("category ILIKE '%charcuterie%'", "Meat"),

    # --- Snacks & Candy ---
    ("category ILIKE '%sweets%'", "Candy"),
    ("category ILIKE 'Snacks & Candy'", "Snacks"),
    ("category ILIKE 'Snacks & Sweets'", "Snacks"),
    ("category ILIKE '%confectionery%'", "Candy"),

    # --- Drinks ---
    ("category ILIKE 'Drinks (Soft%'", "Drinks"),
    ("category ILIKE 'Drinks (Water%'", "Drinks"),
    ("category ILIKE '%Beverages%' AND category != 'Drinks'", "Drinks"),
    ("category ILIKE 'Non-Alcoholic%'", "Drinks"),
    ("category ILIKE '%Soft/Soda%'", "Drinks"),

    # --- Alcohol ---
    ("category ILIKE 'Beer & Wine%'", "Alcohol"),
    ("category ILIKE 'Beer%Wine%'", "Alcohol"),

    # --- Dairy ---
    ("category ILIKE 'Dairy Cheese%'", "Dairy & Eggs"),
    ("category ILIKE 'Dairy, Cheese%'", "Dairy & Eggs"),

    # --- Bakery ---
    ("category ILIKE 'Bakery & Bread'", "Bakery"),
    ("category ILIKE 'Bakery%Bread%'", "Bakery"),

    # --- Pantry ---
    ("category ILIKE 'Pantry Staples%'", "Pantry"),
    ("category ILIKE 'Pantry%Pasta%'", "Pantry"),

    # --- Frozen ---
    ("category ILIKE 'Frozen Foods'", "Frozen"),
    ("category ILIKE 'Frozen Food'", "Frozen"),

    # --- Ready Meals ---
    ("category ILIKE 'Ready Meals & Prepared%'", "Ready Meals"),
    ("category ILIKE '%Prepared Food%' AND category != 'Ready Meals'", "Ready Meals"),

    # --- Household ---
    ("category ILIKE 'Household Consumables%'", "Household"),
    ("category ILIKE 'Household%Paper%'", "Household"),
    ("category ILIKE 'Household%Cleaning%'", "Household"),

    # --- Personal Care ---
    ("category ILIKE 'Personal Hygiene%'", "Personal Care"),
    ("category ILIKE 'Personal Care%Soap%'", "Personal Care"),

    # --- Baby & Kids ---
    ("category ILIKE 'Baby Food%'", "Baby & Kids"),
    ("category ILIKE 'Baby%Formula%'", "Baby & Kids"),

    # --- Pet Supplies ---
    ("category ILIKE 'Pet Food%'", "Pet Supplies"),
    ("category ILIKE 'Pet%Supplies%' AND category != 'Pet Supplies'", "Pet Supplies"),

    # --- Tobacco ---
    ("category ILIKE 'Tobacco Products'", "Tobacco"),

    # --- Other/Unknown ---
    ("category = 'Unknown Transaction'", "Other"),
    ("category ILIKE 'Unknown%'", "Other"),
]

# Valid canonical categories (anything not in this set after cleanup is suspicious)
VALID_CATEGORIES = {
    "Fruits", "Vegetables", "Meat", "Seafood", "Dairy & Eggs", "Bakery",
    "Pantry", "Frozen", "Ready Meals",
    "Snacks", "Candy", "Drinks", "Alcohol",
    "Household", "Personal Care",
    "Baby & Kids", "Pet Supplies", "Tobacco", "Other",
}


def upgrade() -> None:
    for condition, new_name in CLEANUP_RULES:
        op.execute(
            f"UPDATE transactions SET category = '{new_name}' WHERE {condition}"
        )

    # Also clean up budgets.category_allocations JSONB for the most common old names
    budget_renames = [
        ("Fresh Produce", "Vegetables"),
        ("Meat & Seafood", "Meat"),
        ("Snacks & Candy", "Snacks"),
        ("Snacks & Sweets", "Snacks"),
        ("Beverages (Non-Alcoholic)", "Drinks"),
        ("Drinks (Soft/Soda)", "Drinks"),
        ("Beer & Wine (Retail)", "Alcohol"),
        ("Household Consumables (Paper/Cleaning)", "Household"),
        ("Personal Hygiene (Soap/Shampoo)", "Personal Care"),
        ("Baby Food & Formula", "Baby & Kids"),
        ("Pet Food & Supplies", "Pet Supplies"),
        ("Tobacco Products", "Tobacco"),
        ("Unknown Transaction", "Other"),
        ("Frozen Foods", "Frozen"),
        ("Ready Meals & Prepared Food", "Ready Meals"),
        ("Bakery & Bread", "Bakery"),
        ("Pantry Staples (Pasta/Rice/Oil)", "Pantry"),
        ("Meat Poultry & Seafood", "Meat"),
        ("Fresh Produce (Fruit & Veg)", "Vegetables"),
        ("Dairy Cheese & Eggs", "Dairy & Eggs"),
    ]
    for old_name, new_name in budget_renames:
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
    # No reasonable downgrade for a cleanup migration
    pass

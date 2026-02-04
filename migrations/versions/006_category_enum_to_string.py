"""Convert category column from PostgreSQL enum to VARCHAR string

Revision ID: 006_category_enum_to_string
Revises: 005_add_is_me
Create Date: 2026-02-04

Migrates the transactions.category column from a PostgreSQL enum type
to a VARCHAR column with human-readable sub-category names.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "006_category_enum_to_string"
down_revision: Union[str, None] = "005_add_is_me"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mapping from old enum names to new sub-category display strings
ENUM_TO_STRING_MAP = {
    "MEAT_FISH": "Meat Poultry & Seafood",
    "ALCOHOL": "Beer & Wine (Retail)",
    "DRINKS_SOFT_SODA": "Beverages (Non-Alcoholic)",
    "DRINKS_WATER": "Beverages (Non-Alcoholic)",
    "HOUSEHOLD": "Household Consumables (Paper/Cleaning)",
    "SNACKS_SWEETS": "Snacks & Candy",
    "FRESH_PRODUCE": "Fresh Produce (Fruit & Veg)",
    "DAIRY_EGGS": "Dairy Cheese & Eggs",
    "READY_MEALS": "Ready Meals & Prepared Food",
    "BAKERY": "Bakery & Bread",
    "PANTRY": "Pantry Staples (Pasta/Rice/Oil)",
    "PERSONAL_CARE": "Personal Hygiene (Soap/Shampoo)",
    "FROZEN": "Frozen Foods",
    "BABY_KIDS": "Baby Food & Formula",
    "PET_SUPPLIES": "Pet Food & Supplies",
    "TOBACCO": "Tobacco Products",
    "OTHER": "Unknown Transaction",
}

# Reverse mapping for downgrade (best-effort, lossy for duplicates)
STRING_TO_ENUM_MAP = {
    "Meat Poultry & Seafood": "MEAT_FISH",
    "Beer & Wine (Retail)": "ALCOHOL",
    "Beverages (Non-Alcoholic)": "DRINKS_SOFT_SODA",
    "Household Consumables (Paper/Cleaning)": "HOUSEHOLD",
    "Snacks & Candy": "SNACKS_SWEETS",
    "Fresh Produce (Fruit & Veg)": "FRESH_PRODUCE",
    "Dairy Cheese & Eggs": "DAIRY_EGGS",
    "Ready Meals & Prepared Food": "READY_MEALS",
    "Bakery & Bread": "BAKERY",
    "Pantry Staples (Pasta/Rice/Oil)": "PANTRY",
    "Personal Hygiene (Soap/Shampoo)": "PERSONAL_CARE",
    "Frozen Foods": "FROZEN",
    "Baby Food & Formula": "BABY_KIDS",
    "Pet Food & Supplies": "PET_SUPPLIES",
    "Tobacco Products": "TOBACCO",
    "Unknown Transaction": "OTHER",
}


def upgrade() -> None:
    # Step 1: Add new VARCHAR column for the string-based category
    op.add_column(
        "transactions",
        sa.Column("category_str", sa.String(), nullable=True),
    )

    # Step 2: Populate category_str by mapping old enum values to new strings.
    # PostgreSQL stores enum values as the enum name (e.g., 'MEAT_FISH'),
    # so we cast to text first and match against those names.
    op.execute("""
        UPDATE transactions
        SET category_str = CASE category::text
            WHEN 'MEAT_FISH' THEN 'Meat Poultry & Seafood'
            WHEN 'ALCOHOL' THEN 'Beer & Wine (Retail)'
            WHEN 'DRINKS_SOFT_SODA' THEN 'Beverages (Non-Alcoholic)'
            WHEN 'DRINKS_WATER' THEN 'Beverages (Non-Alcoholic)'
            WHEN 'HOUSEHOLD' THEN 'Household Consumables (Paper/Cleaning)'
            WHEN 'SNACKS_SWEETS' THEN 'Snacks & Candy'
            WHEN 'FRESH_PRODUCE' THEN 'Fresh Produce (Fruit & Veg)'
            WHEN 'DAIRY_EGGS' THEN 'Dairy Cheese & Eggs'
            WHEN 'READY_MEALS' THEN 'Ready Meals & Prepared Food'
            WHEN 'BAKERY' THEN 'Bakery & Bread'
            WHEN 'PANTRY' THEN 'Pantry Staples (Pasta/Rice/Oil)'
            WHEN 'PERSONAL_CARE' THEN 'Personal Hygiene (Soap/Shampoo)'
            WHEN 'FROZEN' THEN 'Frozen Foods'
            WHEN 'BABY_KIDS' THEN 'Baby Food & Formula'
            WHEN 'PET_SUPPLIES' THEN 'Pet Food & Supplies'
            WHEN 'TOBACCO' THEN 'Tobacco Products'
            WHEN 'OTHER' THEN 'Unknown Transaction'
            ELSE 'Unknown Transaction'
        END
    """)

    # Step 3: Drop indexes that reference the old category column
    op.execute("DROP INDEX IF EXISTS ix_transactions_category")
    op.execute("DROP INDEX IF EXISTS ix_transactions_user_category")

    # Step 4: Drop the old enum-based category column
    op.drop_column("transactions", "category")

    # Step 5: Rename category_str to category
    op.alter_column("transactions", "category_str", new_column_name="category")

    # Step 6: Set NOT NULL constraint on the new column
    op.alter_column("transactions", "category", nullable=False)

    # Step 7: Create indexes on the new VARCHAR category column
    op.create_index("ix_transactions_category", "transactions", ["category"])
    op.create_index(
        "ix_transactions_user_category", "transactions", ["user_id", "category"]
    )

    # Step 8: Drop the PostgreSQL enum type (no longer needed)
    op.execute("DROP TYPE IF EXISTS category")


def downgrade() -> None:
    # Best-effort downgrade: recreate the enum type and convert back.
    # Note: This is lossy - DRINKS_WATER and DRINKS_SOFT_SODA both map to
    # 'Beverages (Non-Alcoholic)', so we can only recover one of them.

    # Step 1: Recreate the PostgreSQL enum type
    op.execute("""
        CREATE TYPE category AS ENUM (
            'MEAT_FISH', 'ALCOHOL', 'DRINKS_SOFT_SODA', 'DRINKS_WATER',
            'HOUSEHOLD', 'SNACKS_SWEETS', 'FRESH_PRODUCE', 'DAIRY_EGGS',
            'READY_MEALS', 'BAKERY', 'PANTRY', 'PERSONAL_CARE',
            'FROZEN', 'BABY_KIDS', 'PET_SUPPLIES', 'TOBACCO', 'OTHER'
        )
    """)

    # Step 2: Add a temporary enum column
    op.add_column(
        "transactions",
        sa.Column("category_enum", sa.Text(), nullable=True),
    )

    # Step 3: Map string values back to enum names (best-effort)
    op.execute("""
        UPDATE transactions
        SET category_enum = CASE category
            WHEN 'Meat Poultry & Seafood' THEN 'MEAT_FISH'
            WHEN 'Beer & Wine (Retail)' THEN 'ALCOHOL'
            WHEN 'Beverages (Non-Alcoholic)' THEN 'DRINKS_SOFT_SODA'
            WHEN 'Household Consumables (Paper/Cleaning)' THEN 'HOUSEHOLD'
            WHEN 'Snacks & Candy' THEN 'SNACKS_SWEETS'
            WHEN 'Fresh Produce (Fruit & Veg)' THEN 'FRESH_PRODUCE'
            WHEN 'Dairy Cheese & Eggs' THEN 'DAIRY_EGGS'
            WHEN 'Ready Meals & Prepared Food' THEN 'READY_MEALS'
            WHEN 'Bakery & Bread' THEN 'BAKERY'
            WHEN 'Pantry Staples (Pasta/Rice/Oil)' THEN 'PANTRY'
            WHEN 'Personal Hygiene (Soap/Shampoo)' THEN 'PERSONAL_CARE'
            WHEN 'Frozen Foods' THEN 'FROZEN'
            WHEN 'Baby Food & Formula' THEN 'BABY_KIDS'
            WHEN 'Pet Food & Supplies' THEN 'PET_SUPPLIES'
            WHEN 'Tobacco Products' THEN 'TOBACCO'
            ELSE 'OTHER'
        END
    """)

    # Step 4: Drop indexes on the VARCHAR category column
    op.execute("DROP INDEX IF EXISTS ix_transactions_category")
    op.execute("DROP INDEX IF EXISTS ix_transactions_user_category")

    # Step 5: Drop the VARCHAR category column
    op.drop_column("transactions", "category")

    # Step 6: Rename category_enum to category and cast to the enum type
    op.execute("""
        ALTER TABLE transactions
        RENAME COLUMN category_enum TO category
    """)
    op.execute("""
        ALTER TABLE transactions
        ALTER COLUMN category TYPE category USING category::category
    """)
    op.execute("""
        ALTER TABLE transactions
        ALTER COLUMN category SET NOT NULL
    """)

    # Step 7: Recreate indexes
    op.create_index("ix_transactions_category", "transactions", ["category"])
    op.create_index(
        "ix_transactions_user_category", "transactions", ["user_id", "category"]
    )

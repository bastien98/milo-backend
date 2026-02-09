"""Fix parent category names from categories.py mapping

Revision ID: 014_fix_parents
Revises: 013_cleanup_categories
Create Date: 2026-02-09

Updates transactions that still have old parent category names from
the GRANULAR_CATEGORIES mapping (Meat & Fish, Fresh Produce,
Snacks & Sweets, Drinks (Soft/Soda), Drinks (Water)).
Uses granular_category column for accurate splits.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "014_fix_parents"
down_revision: Union[str, None] = "013_cleanup_categories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Meat & Fish → Meat / Seafood ---
    # Fish items → Seafood
    op.execute("""
        UPDATE transactions SET category = 'Seafood'
        WHERE category = 'Meat & Fish'
        AND (granular_category ILIKE 'Fish%'
             OR granular_category ILIKE 'Shellfish%'
             OR granular_category ILIKE 'Canned Fish%'
             OR granular_category ILIKE 'Surimi%')
    """)
    # Remaining Meat & Fish → Meat
    op.execute("""
        UPDATE transactions SET category = 'Meat'
        WHERE category = 'Meat & Fish'
    """)

    # --- Fresh Produce → Fruits / Vegetables ---
    # Fruit items → Fruits
    op.execute("""
        UPDATE transactions SET category = 'Fruits'
        WHERE category = 'Fresh Produce'
        AND (granular_category ILIKE 'Fruit%'
             OR granular_category ILIKE 'Nuts')
    """)
    # Remaining Fresh Produce → Vegetables
    op.execute("""
        UPDATE transactions SET category = 'Vegetables'
        WHERE category = 'Fresh Produce'
    """)

    # --- Snacks & Sweets → Snacks / Candy ---
    # Candy items → Candy
    op.execute("""
        UPDATE transactions SET category = 'Candy'
        WHERE category = 'Snacks & Sweets'
        AND (granular_category ILIKE 'Chocolate%'
             OR granular_category ILIKE 'Candy%'
             OR granular_category ILIKE 'Licorice%'
             OR granular_category ILIKE 'Gum%'
             OR granular_category ILIKE 'Marshmallow%')
    """)
    # Remaining Snacks & Sweets → Snacks
    op.execute("""
        UPDATE transactions SET category = 'Snacks'
        WHERE category = 'Snacks & Sweets'
    """)

    # --- Drinks (Soft/Soda) and Drinks (Water) → Drinks ---
    op.execute("""
        UPDATE transactions SET category = 'Drinks'
        WHERE category IN ('Drinks (Soft/Soda)', 'Drinks (Water)')
    """)

    # --- Catch-all for any remaining old names ---
    op.execute("UPDATE transactions SET category = 'Meat' WHERE category ILIKE 'Meat%Fish%'")
    op.execute("UPDATE transactions SET category = 'Meat' WHERE category ILIKE 'Meat%Seafood%'")
    op.execute("UPDATE transactions SET category = 'Drinks' WHERE category ILIKE 'Drinks%Soft%'")
    op.execute("UPDATE transactions SET category = 'Drinks' WHERE category ILIKE 'Drinks%Water%'")


def downgrade() -> None:
    # No reasonable downgrade for a cleanup migration
    pass

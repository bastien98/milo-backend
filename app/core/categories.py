"""
Category definitions — single source of truth for the entire app.

Three-level hierarchy:
  Group (8)  →  Category / Parent (31)  →  Granular (~200)

Everything is defined once in _TREE below. All lookup dicts and constants
are derived from it at module load time.

Groups provide coarse visual grouping (section headers, group-level SF Symbol icons).
Categories have their own Phosphor icon and hex color (cross-platform: iOS + Android).
Categories are what transactions store in the database.
Granular categories are used by LLM prompts for fine-grained classification.
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, List, Optional


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass(frozen=True)
class CategoryInfo:
    """Full metadata for a parent category."""
    name: str               # Internal name (stored in DB), e.g. "Meat & Poultry (Raw)"
    display_name: str       # Clean display name, e.g. "Meat & Poultry"
    group: str              # Group name, e.g. "Fresh Food"
    color_hex: str          # Group color (hex)
    icon: str               # Group icon (SF Symbol)
    category_icon: str      # Per-category icon (Phosphor, kebab-case)
    category_color_hex: str # Per-category color (hex)


# ============================================================
# SINGLE SOURCE OF TRUTH
# ============================================================
#
# Structure: list of groups, each containing its categories,
# each category containing its granular sub-categories.
#
# Group fields:
#   group      — Group name (section header)
#   color      — Hex color for the group
#   icon       — SF Symbol icon for the group
#   categories — List of parent categories in this group
#
# Category fields:
#   name       — Internal DB name (e.g. "Meat & Poultry (Raw)")
#   display    — Clean display name (e.g. "Meat & Poultry")
#   icon       — Phosphor icon (kebab-case, cross-platform)
#   color      — Hex color for this specific category
#   granular   — List of granular sub-category names (used by LLM)
#   excluded   — (optional) If True, excluded from analytics/budgets

_TREE = [

    # ── Fresh Food ───────────────────────────────────────────
    {
        "group": "Fresh Food",
        "color": "#2ECC71",
        "icon": "leaf.fill",
        "categories": [
            {
                "name": "Fruits",
                "display": "Fruits",
                "icon": "apple-logo",
                "color": "#34D399",
                "granular": [
                    "Fruit Apples Pears",
                    "Fruit Citrus",
                    "Fruit Bananas",
                    "Fruit Berries",
                    "Fruit Stone",
                    "Fruit Grapes",
                    "Fruit Melons",
                    "Fruit Tropical",
                    "Fruit Dried",
                    "Nuts",
                ],
            },
            {
                "name": "Vegetables",
                "display": "Vegetables",
                "icon": "carrot",
                "color": "#16A34A",
                "granular": [
                    "Tomatoes",
                    "Salad & Leafy Greens",
                    "Cucumber & Peppers",
                    "Onions & Garlic",
                    "Carrots & Root Veg",
                    "Potatoes",
                    "Cabbage & Broccoli",
                    "Beans & Peas",
                    "Mushrooms",
                    "Zucchini & Eggplant",
                    "Corn",
                    "Fresh Herbs",
                    "Prepared Vegetables",
                ],
            },
            {
                "name": "Meat & Poultry (Raw)",
                "display": "Meat & Poultry",
                "icon": "steak",
                "color": "#FB923C",
                "granular": [
                    "Beef",
                    "Pork",
                    "Chicken",
                    "Turkey",
                    "Lamb",
                    "Minced Meat",
                    "Meat Preparations",
                    "Offal",
                ],
            },
            {
                "name": "Charcuterie & Salads (Preparé/Deli)",
                "display": "Charcuterie & Salads",
                "icon": "sandwich",
                "color": "#F87171",
                "granular": [
                    "Ham Cooked",
                    "Ham Dry",
                    "Salami & Sausage",
                    "Pâté & Terrine",
                    "Bacon & Lardons",
                    "Chicken Turkey Deli",
                    "Vegetarian Deli",
                    "Meals Salads",
                    "Sandwiches",
                    "Sushi",
                    "Hummus & Dips",
                ],
            },
            {
                "name": "Fish & Seafood",
                "display": "Fish & Seafood",
                "icon": "fish",
                "color": "#22D3EE",
                "granular": [
                    "Fish Fresh",
                    "Fish Smoked",
                    "Fish Frozen",
                    "Shellfish",
                    "Canned Fish",
                    "Surimi",
                ],
            },
            {
                "name": "Dairy, Eggs & Cheese",
                "display": "Dairy, Eggs & Cheese",
                "icon": "cheese",
                "color": "#FACC15",
                "granular": [
                    "Plant Milk",
                    "Milk Fresh",
                    "Milk Long Life",
                    "Cream",
                    "Yoghurt Natural",
                    "Yoghurt Fruit",
                    "Yoghurt Drinks",
                    "Skyr & Quark",
                    "Pudding & Desserts",
                    "Butter",
                    "Margarine",
                    "Cooking Fat",
                    "Cheese Hard",
                    "Cheese Soft",
                    "Cheese Blue",
                    "Cheese Fresh",
                    "Cheese Spread",
                    "Cheese Sliced",
                    "Cheese Grated",
                    "Cheese Belgian",
                    "Eggs",
                    "Vegan Cheese Dairy",
                    "Protein Shakes",
                    "Protein Desserts",
                ],
            },
            {
                "name": "Bakery (Bread, Pistolets)",
                "display": "Bakery",
                "icon": "bread",
                "color": "#F59E0B",
                "granular": [
                    "Bread Fresh",
                    "Bread Sliced",
                    "Bread Specialty",
                    "Wraps & Pita",
                    "Crackers",
                ],
            },
            {
                "name": "Pastries & Koffiekoeken",
                "display": "Pastries",
                "icon": "cake",
                "color": "#FB7185",
                "granular": [
                    "Croissants & Pastries",
                    "Cakes & Tarts",
                    "Waffles",
                ],
            },
        ],
    },

    # ── Pantry & Staples ─────────────────────────────────────
    {
        "group": "Pantry & Staples",
        "color": "#E67E22",
        "icon": "cabinet.fill",
        "categories": [
            {
                "name": "Grains, Pasta & Potatoes",
                "display": "Grains, Pasta & Potatoes",
                "icon": "grains",
                "color": "#D97706",
                "granular": [
                    "Pasta Dry",
                    "Pasta Fresh",
                    "Rice",
                    "Noodles Asian",
                    "Couscous & Bulgur",
                    "Grains & Legumes",
                ],
            },
            {
                "name": "Canned & Jarred Goods",
                "display": "Canned & Jarred Goods",
                "icon": "jar",
                "color": "#84CC16",
                "granular": [
                    "Canned Tomatoes",
                    "Canned Vegetables",
                    "Canned Beans",
                    "Canned Fruits",
                    "Pickles & Olives",
                    "Jarred Antipasti",
                    "Soup Canned",
                    "Soup Carton Fresh",
                    "Soup Instant",
                ],
            },
            {
                "name": "Sauces, Mayo & Condiments",
                "display": "Sauces & Condiments",
                "icon": "pepper",
                "color": "#EA580C",
                "granular": [
                    "Pasta Sauce",
                    "Tomato Sauce & Ketchup",
                    "Mayonnaise",
                    "Mustard",
                    "Soy & Asian Sauce",
                    "BBQ Sauce",
                    "Salad Dressing",
                    "Vinegar",
                    "Olive Oil",
                    "Cooking Oil",
                    "Salt Pepper & Spices",
                    "Stock & Bouillon",
                    "Dried Herbs",
                ],
            },
            {
                "name": "Breakfast & Cereal (Choco/Jam)",
                "display": "Breakfast & Cereal",
                "icon": "bowl-food",
                "color": "#EAB308",
                "granular": [
                    "Cereals",
                    "Oatmeal",
                    "Spreads Chocolate",
                    "Spreads Jam",
                    "Spreads Honey",
                    "Spreads Peanut Nut",
                    "Spreads Savory",
                ],
            },
            {
                "name": "Baking & Flour",
                "display": "Baking & Flour",
                "icon": "chef-hat",
                "color": "#C4A57B",
                "granular": [
                    "Flour",
                    "Sugar",
                    "Baking Ingredients",
                    "Baking Decorations",
                    "Chocolate Baking",
                ],
            },
        ],
    },

    # ── Frozen ───────────────────────────────────────────────
    {
        "group": "Frozen",
        "color": "#3498DB",
        "icon": "snowflake",
        "categories": [
            {
                "name": "Frozen Ingredients (Veg/Fruit)",
                "display": "Frozen Ingredients",
                "icon": "snowflake",
                "color": "#0891B2",
                "granular": [
                    "Frozen Vegetables",
                    "Frozen Fish",
                    "Frozen Meat",
                    "Frozen Bread",
                    "Frozen Fruits",
                    "Ice Cream",
                    "Frozen Desserts",
                ],
            },
            {
                "name": "Fries & Snacks (Frituur at home)",
                "display": "Fries & Snacks",
                "icon": "french-fries",
                "color": "#EF4444",
                "granular": [
                    "Frozen Fries",
                    "Frozen Snacks",
                ],
            },
            {
                "name": "Ready Meals & Pizza",
                "display": "Ready Meals & Pizza",
                "icon": "pizza",
                "color": "#F97316",
                "granular": [
                    "Frozen Pizza",
                    "Frozen Meals",
                    "Meals Fresh",
                    "Pizza Fresh",
                    "Meat Substitute",
                    "Vegetarian Meals",
                    "Asian Food",
                    "Mexican Food",
                    "Italian Specialty",
                    "Middle Eastern",
                ],
            },
        ],
    },

    # ── Drinks ───────────────────────────────────────────────
    {
        "group": "Drinks",
        "color": "#E74C3C",
        "icon": "mug.fill",
        "categories": [
            {
                "name": "Water (Bottled)",
                "display": "Water",
                "icon": "drop-half-bottom",
                "color": "#38BDF8",
                "granular": [
                    "Water Still",
                    "Water Sparkling",
                    "Water Flavored",
                ],
            },
            {
                "name": "Soda & Juices",
                "display": "Soda & Juices",
                "icon": "soda-can",
                "color": "#F472B6",
                "granular": [
                    "Cola",
                    "Lemonade & Soda",
                    "Energy Drinks",
                    "Ice Tea",
                    "Fruit Juice",
                    "Vegetable Juice",
                    "Smoothies",
                    "Syrup",
                    "Beer Non-Alcoholic",
                ],
            },
            {
                "name": "Coffee & Tea",
                "display": "Coffee & Tea",
                "icon": "coffee",
                "color": "#A8896C",
                "granular": [
                    "Coffee Beans Ground",
                    "Coffee Capsules",
                    "Coffee Instant",
                    "Tea",
                    "Hot Chocolate",
                ],
            },
            {
                "name": "Alcohol (Beer, Cider, Wine, Whisky, Vodka, Gin, Cava, Champagne)",
                "display": "Alcohol",
                "icon": "wine",
                "color": "#DC2626",
                "granular": [
                    "Beer Pils",
                    "Beer Abbey Trappist",
                    "Beer Special",
                    "Beer White Fruit",
                    "Cider",
                    "Wine Red",
                    "Wine White",
                    "Wine Rosé",
                    "Wine Sparkling",
                    "Spirits Whisky",
                    "Spirits Gin",
                    "Spirits Vodka",
                    "Spirits Rum",
                    "Spirits Liqueur",
                    "Aperitif",
                ],
            },
        ],
    },

    # ── Snacks ───────────────────────────────────────────────
    {
        "group": "Snacks",
        "color": "#F39C12",
        "icon": "popcorn.fill",
        "categories": [
            {
                "name": "Chips, Nuts & Aperitif",
                "display": "Chips, Nuts & Aperitif",
                "icon": "popcorn",
                "color": "#E85D5D",
                "granular": [
                    "Chips",
                    "Nuts Snack",
                    "Crackers Snack",
                    "Popcorn",
                    "Dried Meat Snack",
                    "Protein Bars",
                ],
            },
            {
                "name": "Chocolate & Sweets (Biscuits)",
                "display": "Chocolate, Biscuits & Sweets",
                "icon": "candy",
                "color": "#EC4899",
                "granular": [
                    "Cookies & Biscuits",
                    "Chocolate Bars",
                    "Chocolate Pralines",
                    "Candy",
                    "Licorice",
                    "Gum & Mints",
                    "Marshmallows",
                ],
            },
        ],
    },

    # ── Household ────────────────────────────────────────────
    {
        "group": "Household",
        "color": "#8E44AD",
        "icon": "bubbles.and.sparkles.fill",
        "categories": [
            {
                "name": "Official Waste Bags (PMD/Rest)",
                "display": "Waste Bags",
                "icon": "trash",
                "color": "#78909C",
                "granular": [
                    "Trash Bags",
                ],
            },
            {
                "name": "Cleaning & Paper Goods",
                "display": "Cleaning & Paper Goods",
                "icon": "toilet-paper",
                "color": "#A855F7",
                "granular": [
                    "Cleaning All-Purpose",
                    "Cleaning Kitchen",
                    "Cleaning Bathroom",
                    "Cleaning Floor",
                    "Cleaning Glass",
                    "Cleaning WC",
                    "Cleaning Tools",
                    "Laundry Detergent",
                    "Laundry Softener",
                    "Laundry Stain Remover",
                    "Laundry Ironing",
                    "Toilet Paper",
                    "Kitchen Paper",
                    "Tissues",
                    "Napkins",
                    "Kitchen Accessories",
                ],
            },
        ],
    },

    # ── Personal Care ────────────────────────────────────────
    {
        "group": "Personal Care",
        "color": "#1ABC9C",
        "icon": "heart.fill",
        "categories": [
            {
                "name": "Pharmacy & Hygiene",
                "display": "Pharmacy & Hygiene",
                "icon": "first-aid",
                "color": "#8B5CF6",
                "granular": [
                    "Shower Gel",
                    "Soap",
                    "Deodorant",
                    "Body Lotion",
                    "Sunscreen",
                    "Shampoo",
                    "Conditioner",
                    "Hair Styling",
                    "Hair Color",
                    "Face Care",
                    "Toothpaste",
                    "Toothbrush",
                    "Mouthwash",
                    "Shaving",
                    "Feminine Hygiene",
                    "Contraception",
                    "First Aid",
                    "Vitamins & Supplements",
                    "Pain Relief",
                ],
            },
        ],
    },

    # ── Other ────────────────────────────────────────────────
    {
        "group": "Other",
        "color": "#95A5A6",
        "icon": "square.grid.2x2.fill",
        "categories": [
            {
                "name": "Baby & Kids",
                "display": "Baby & Kids",
                "icon": "baby",
                "color": "#3B82F6",
                "granular": [
                    "Baby Milk",
                    "Baby Food",
                    "Baby Snacks",
                    "Diapers",
                    "Baby Care",
                ],
            },
            {
                "name": "Pet Supplies",
                "display": "Pet Supplies",
                "icon": "paw-print",
                "color": "#64748B",
                "granular": [
                    "Pet Food Dog",
                    "Pet Food Cat",
                    "Pet Treats",
                    "Pet Litter",
                    "Pet Care",
                ],
            },
            {
                "name": "Tobacco",
                "display": "Tobacco",
                "icon": "cigarette",
                "color": "#B91C1C",
                "granular": [
                    "Tobacco",
                ],
            },
            {
                "name": "Lottery & Scratch Cards",
                "display": "Lottery & Scratch Cards",
                "icon": "ticket",
                "color": "#94A3B8",
                "granular": [
                    "Lottery & Scratch Cards",
                ],
            },
            {
                "name": "Promos & Discounts",
                "display": "Promos & Discounts",
                "icon": "percent",
                "color": "#94A3B8",
                "excluded": True,
                "granular": [
                    "Discount",
                    "Coupon",
                    "Loyalty Discount",
                    "Promotional Offer",
                    "Multi-Buy Deal",
                ],
            },
            {
                "name": "Deposits (Statiegeld/Vidange)",
                "display": "Deposits",
                "icon": "recycle",
                "color": "#94A3B8",
                "excluded": True,
                "granular": [
                    "Bottle Deposit",
                    "Can Deposit",
                    "Crate Deposit",
                    "Deposit Refund",
                ],
            },
            {
                "name": "Other",
                "display": "Other",
                "icon": "dots-three-circle",
                "color": "#94A3B8",
                "granular": [
                    "Batteries",
                    "Lightbulbs",
                    "Party Supplies",
                    "Flowers & Plants",
                    "Other",
                ],
            },
        ],
    },
]


# ============================================================
# DERIVED LOOKUPS (built once at module load time from _TREE)
# ============================================================

GROUP_COLORS: Dict[str, str] = {}
GROUP_ICONS: Dict[str, str] = {}
CATEGORY_ICONS: Dict[str, str] = {}
CATEGORY_COLORS: Dict[str, str] = {}
GRANULAR_CATEGORIES: Dict[str, str] = {}
EXCLUDED_CATEGORIES: frozenset

_HIERARCHY: Dict[str, List[tuple]] = {}
_CATEGORY_LOOKUP: Dict[str, CategoryInfo] = {}
_LOWER_LOOKUP: Dict[str, str] = {}
_DISPLAY_LOOKUP: Dict[str, str] = {}
_ALL_CATEGORIES: List[str] = []


def _build_lookups() -> None:
    """Build all lookup tables from _TREE at module load time."""
    excluded = set()

    for group in _TREE:
        group_name = group["group"]
        group_color = group["color"]
        group_icon = group["icon"]

        # Group-level dicts
        GROUP_COLORS[group_name] = group_color
        GROUP_ICONS[group_name] = group_icon

        # Hierarchy (for backward compat)
        hierarchy_entries = []

        for cat in group["categories"]:
            cat_name = cat["name"]
            display_name = cat["display"]
            cat_icon = cat["icon"]
            cat_color = cat["color"]

            # Category-level dicts
            CATEGORY_ICONS[cat_name] = cat_icon
            CATEGORY_COLORS[cat_name] = cat_color

            # Hierarchy entry
            hierarchy_entries.append((cat_name, display_name))

            # Excluded flag
            if cat.get("excluded"):
                excluded.add(cat_name)

            # Granular → parent mapping
            for granular in cat.get("granular", []):
                GRANULAR_CATEGORIES[granular] = cat_name

            # CategoryInfo lookup
            info = CategoryInfo(
                name=cat_name,
                display_name=display_name,
                group=group_name,
                color_hex=group_color,
                icon=group_icon,
                category_icon=cat_icon,
                category_color_hex=cat_color,
            )
            _CATEGORY_LOOKUP[cat_name] = info
            _LOWER_LOOKUP[cat_name.lower()] = cat_name
            _DISPLAY_LOOKUP[display_name] = cat_name
            _DISPLAY_LOOKUP[display_name.lower()] = cat_name
            _ALL_CATEGORIES.append(cat_name)

        _HIERARCHY[group_name] = hierarchy_entries

    global EXCLUDED_CATEGORIES
    EXCLUDED_CATEGORIES = frozenset(excluded)


_build_lookups()


# ============================================================
# PROMPT HELPERS
# ============================================================

# Granular-level prompt list (for promo extraction and vision service)
CATEGORIES_PROMPT_LIST: str = "\n".join(
    f"- {cat}" for cat in GRANULAR_CATEGORIES.keys()
)

# Parent-level prompt list (for receipt categorization)
PARENT_CATEGORIES_PROMPT_LIST: str = "\n".join(
    f"- \"{info.name}\"" for info in _CATEGORY_LOOKUP.values()
)


# ============================================================
# PUBLIC API - Granular category functions
# ============================================================

def get_parent_category(granular: str) -> str:
    """Get parent category for a granular category, defaulting to 'Other'."""
    return GRANULAR_CATEGORIES.get(granular, "Other")


def get_all_granular_categories() -> List[str]:
    """Get list of all valid granular categories."""
    return list(GRANULAR_CATEGORIES.keys())


def validate_granular_category(granular: str) -> bool:
    """Check if a granular category is valid."""
    return granular in GRANULAR_CATEGORIES


# ============================================================
# PUBLIC API - Parent category functions
# ============================================================

def get_category_info(category: str) -> Optional[CategoryInfo]:
    """Get full info for a parent category (case-insensitive)."""
    info = _CATEGORY_LOOKUP.get(category)
    if info:
        return info
    canonical = _LOWER_LOOKUP.get(category.lower())
    if canonical:
        return _CATEGORY_LOOKUP[canonical]
    return None


def get_display_name(category: str) -> str:
    """Get clean display name for a category."""
    info = get_category_info(category)
    return info.display_name if info else category


def get_group(category: str) -> Optional[str]:
    """Get the group name for a category."""
    info = get_category_info(category)
    return info.group if info else None


def get_group_color(category: str) -> str:
    """Get hex color for a category based on its group."""
    info = get_category_info(category)
    return info.color_hex if info else "#BDC3C7"


def get_group_icon(category: str) -> str:
    """Get SF Symbol icon for a category based on its group."""
    info = get_category_info(category)
    return info.icon if info else "square.grid.2x2.fill"


def get_category_icon(category: str) -> str:
    """Get Phosphor icon name for a specific category (cross-platform)."""
    info = get_category_info(category)
    return info.category_icon if info else "tag"


def get_category_color(category: str) -> str:
    """Get hex color for a specific category."""
    info = get_category_info(category)
    return info.category_color_hex if info else "#8E8E93"


def get_internal_name(category: str) -> Optional[str]:
    """Resolve a category string to its internal name (the key stored in the DB).

    Accepts internal names, display names, or lowercase variants of either.
    Returns None if no match is found.
    """
    if category in _CATEGORY_LOOKUP:
        return category
    if category in _DISPLAY_LOOKUP:
        return _DISPLAY_LOOKUP[category]
    lower = category.lower()
    if lower in _LOWER_LOOKUP:
        return _LOWER_LOOKUP[lower]
    if lower in _DISPLAY_LOOKUP:
        return _DISPLAY_LOOKUP[lower]
    return None


def is_valid_category(category: str) -> bool:
    """Check if a parent category name is valid (case-insensitive)."""
    if category in _CATEGORY_LOOKUP:
        return True
    return category.lower() in _LOWER_LOOKUP


def get_all_categories() -> List[str]:
    """Get all parent category names."""
    return _ALL_CATEGORIES.copy()


def get_all_groups() -> List[str]:
    """Get all group names."""
    return list(_HIERARCHY.keys())


def get_categories_for_group(group: str) -> List[str]:
    """Get all category names in a group."""
    entries = _HIERARCHY.get(group, [])
    return [name for name, _ in entries]


def get_category_id(category: str) -> str:
    """Generate a stable UPPER_SNAKE_CASE ID from a category's display name.

    e.g. "Meat & Poultry" -> "MEAT_POULTRY"
    """
    s = get_display_name(category).upper()
    s = s.replace("(", "").replace(")", "")
    for ch in "&/-,.":
        s = s.replace(ch, "_")
    s = re.sub(r"[\s_]+", "_", s)
    s = s.strip("_")
    return s


def find_closest_match(name: str, threshold: float = 0.6) -> Optional[str]:
    """Find closest matching parent category using fuzzy matching."""
    if is_valid_category(name):
        canonical = _LOWER_LOOKUP.get(name.lower())
        return canonical if canonical else name

    best_match = None
    best_score = 0.0
    name_lower = name.lower()

    for cat in _ALL_CATEGORIES:
        score = SequenceMatcher(None, name_lower, cat.lower()).ratio()
        if score > best_score and score >= threshold:
            best_score = score
            best_match = cat

    return best_match


def get_hierarchy() -> dict:
    """Get the full hierarchy as a dict for API responses."""
    groups = []
    for group in _TREE:
        group_name = group["group"]
        cat_list = []
        for cat in group["categories"]:
            cat_list.append({
                "name": cat["name"],
                "display_name": cat["display"],
                "sub_categories": [cat["name"]],
                "icon": cat["icon"],
                "color_hex": cat["color"],
                "budgetable": not cat.get("excluded", False),
            })
        groups.append({
            "name": group_name,
            "icon": group["icon"],
            "color_hex": group["color"],
            "categories": cat_list,
        })
    return {"groups": groups}

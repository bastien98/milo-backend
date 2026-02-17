"""
Category definitions - single source of truth for the entire app.

Three-level hierarchy:
  Group (8)  -->  Category / Parent (31)  -->  Granular (~200)

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
# GROUP-LEVEL CONSTANTS
# ============================================================

GROUP_COLORS: Dict[str, str] = {
    "Fresh Food": "#2ECC71",
    "Pantry & Staples": "#E67E22",
    "Frozen": "#3498DB",
    "Drinks": "#E74C3C",
    "Snacks": "#F39C12",
    "Household": "#8E44AD",
    "Personal Care": "#1ABC9C",
    "Other": "#95A5A6",
}

GROUP_ICONS: Dict[str, str] = {
    "Fresh Food": "leaf.fill",
    "Pantry & Staples": "cabinet.fill",
    "Frozen": "snowflake",
    "Drinks": "mug.fill",
    "Snacks": "popcorn.fill",
    "Household": "bubbles.and.sparkles.fill",
    "Personal Care": "heart.fill",
    "Other": "square.grid.2x2.fill",
}


# ============================================================
# CATEGORY-LEVEL CONSTANTS (Phosphor icons + individual colors)
# ============================================================

CATEGORY_ICONS: Dict[str, str] = {
    "Fruits": "apple-logo",
    "Vegetables": "carrot",
    "Meat & Poultry (Raw)": "bone",
    "Charcuterie & Salads (Preparé/Deli)": "bowl-food",
    "Fish & Seafood": "fish",
    "Dairy, Eggs & Cheese": "cheese",
    "Bakery (Bread, Pistolets)": "bread",
    "Pastries & Koffiekoeken": "cookie",
    "Grains, Pasta & Potatoes": "grains",
    "Canned & Jarred Goods": "jar",
    "Sauces, Mayo & Condiments": "drop",
    "Breakfast & Cereal (Choco/Jam)": "sun",
    "Baking & Flour": "cooking-pot",
    "Frozen Ingredients (Veg/Fruit)": "snowflake",
    "Fries & Snacks (Frituur at home)": "fire",
    "Ready Meals & Pizza": "pizza",
    "Water (Bottled)": "drop",
    "Soda & Juices": "orange-slice",
    "Coffee & Tea": "coffee",
    "Alcohol (Beer, Cider, Wine, Whisky, Vodka, Gin, Cava, Champagne)": "wine",
    "Chips, Nuts & Aperitif": "popcorn",
    "Chocolate & Sweets (Biscuits)": "cookie",
    "Official Waste Bags (PMD/Rest)": "trash",
    "Cleaning & Paper Goods": "sparkle",
    "Pharmacy & Hygiene": "pill",
    "Baby & Kids": "baby",
    "Pet Supplies": "paw-print",
    "Tobacco": "cigarette",
    "Lottery & Scratch Cards": "ticket",
    "Promos & Discounts": "percent",
    "Deposits (Statiegeld/Vidange)": "recycle",
    "Other": "tag",
}

CATEGORY_COLORS: Dict[str, str] = {
    "Fruits": "#FF9500",
    "Vegetables": "#34C759",
    "Meat & Poultry (Raw)": "#FF3B30",
    "Charcuterie & Salads (Preparé/Deli)": "#FF2D55",
    "Fish & Seafood": "#007AFF",
    "Dairy, Eggs & Cheese": "#FFCC00",
    "Bakery (Bread, Pistolets)": "#A2845E",
    "Pastries & Koffiekoeken": "#AF52DE",
    "Grains, Pasta & Potatoes": "#999999",
    "Canned & Jarred Goods": "#8E8E93",
    "Sauces, Mayo & Condiments": "#E63333",
    "Breakfast & Cereal (Choco/Jam)": "#E69933",
    "Baking & Flour": "#CCCCCC",
    "Frozen Ingredients (Veg/Fruit)": "#5AC8FA",
    "Fries & Snacks (Frituur at home)": "#FFCC00",
    "Ready Meals & Pizza": "#FF9500",
    "Water (Bottled)": "#007AFF",
    "Soda & Juices": "#FF2D55",
    "Coffee & Tea": "#A2845E",
    "Alcohol (Beer, Cider, Wine, Whisky, Vodka, Gin, Cava, Champagne)": "#AF52DE",
    "Chips, Nuts & Aperitif": "#FFCC00",
    "Chocolate & Sweets (Biscuits)": "#A2845E",
    "Official Waste Bags (PMD/Rest)": "#8E8E93",
    "Cleaning & Paper Goods": "#00C7BE",
    "Pharmacy & Hygiene": "#FF3B30",
    "Baby & Kids": "#30B0C7",
    "Pet Supplies": "#FF9500",
    "Tobacco": "#8E8E93",
    "Lottery & Scratch Cards": "#5856D6",
    "Promos & Discounts": "#30D158",
    "Deposits (Statiegeld/Vidange)": "#34C759",
    "Other": "#8E8E93",
}


# ============================================================
# CATEGORY HIERARCHY (replaces categories.csv)
# ============================================================
# Dict[group_name, List[Tuple[category_name, display_name]]]

_HIERARCHY: Dict[str, List[tuple]] = {
    "Fresh Food": [
        ("Fruits", "Fruits"),
        ("Vegetables", "Vegetables"),
        ("Meat & Poultry (Raw)", "Meat & Poultry"),
        ("Charcuterie & Salads (Preparé/Deli)", "Charcuterie & Salads"),
        ("Fish & Seafood", "Fish & Seafood"),
        ("Dairy, Eggs & Cheese", "Dairy, Eggs & Cheese"),
        ("Bakery (Bread, Pistolets)", "Bakery"),
        ("Pastries & Koffiekoeken", "Pastries"),
    ],
    "Pantry & Staples": [
        ("Grains, Pasta & Potatoes", "Grains, Pasta & Potatoes"),
        ("Canned & Jarred Goods", "Canned & Jarred Goods"),
        ("Sauces, Mayo & Condiments", "Sauces & Condiments"),
        ("Breakfast & Cereal (Choco/Jam)", "Breakfast & Cereal"),
        ("Baking & Flour", "Baking & Flour"),
    ],
    "Frozen": [
        ("Frozen Ingredients (Veg/Fruit)", "Frozen Ingredients"),
        ("Fries & Snacks (Frituur at home)", "Fries & Snacks"),
        ("Ready Meals & Pizza", "Ready Meals & Pizza"),
    ],
    "Drinks": [
        ("Water (Bottled)", "Water"),
        ("Soda & Juices", "Soda & Juices"),
        ("Coffee & Tea", "Coffee & Tea"),
        ("Alcohol (Beer, Cider, Wine, Whisky, Vodka, Gin, Cava, Champagne)", "Alcohol"),
    ],
    "Snacks": [
        ("Chips, Nuts & Aperitif", "Chips, Nuts & Aperitif"),
        ("Chocolate & Sweets (Biscuits)", "Chocolate, Biscuits & Sweets"),
    ],
    "Household": [
        ("Official Waste Bags (PMD/Rest)", "Waste Bags"),
        ("Cleaning & Paper Goods", "Cleaning & Paper Goods"),
    ],
    "Personal Care": [
        ("Pharmacy & Hygiene", "Pharmacy & Hygiene"),
    ],
    "Other": [
        ("Baby & Kids", "Baby & Kids"),
        ("Pet Supplies", "Pet Supplies"),
        ("Tobacco", "Tobacco"),
        ("Lottery & Scratch Cards", "Lottery & Scratch Cards"),
        ("Promos & Discounts", "Promos & Discounts"),
        ("Deposits (Statiegeld/Vidange)", "Deposits"),
        ("Other", "Other"),
    ],
}


# ============================================================
# PARENT CATEGORY NAME CONSTANTS (for GRANULAR_CATEGORIES mapping)
# ============================================================

_FRUITS = "Fruits"
_VEGETABLES = "Vegetables"
_MEAT_RAW = "Meat & Poultry (Raw)"
_CHARCUTERIE = "Charcuterie & Salads (Preparé/Deli)"
_FISH = "Fish & Seafood"
_DAIRY = "Dairy, Eggs & Cheese"
_BAKERY = "Bakery (Bread, Pistolets)"
_PASTRIES = "Pastries & Koffiekoeken"
_GRAINS = "Grains, Pasta & Potatoes"
_CANNED = "Canned & Jarred Goods"
_SAUCES = "Sauces, Mayo & Condiments"
_BREAKFAST = "Breakfast & Cereal (Choco/Jam)"
_BAKING = "Baking & Flour"
_FROZEN_INGR = "Frozen Ingredients (Veg/Fruit)"
_FRIES = "Fries & Snacks (Frituur at home)"
_READY_MEALS = "Ready Meals & Pizza"
_WATER = "Water (Bottled)"
_SODA = "Soda & Juices"
_COFFEE = "Coffee & Tea"
_ALCOHOL = "Alcohol (Beer, Cider, Wine, Whisky, Vodka, Gin, Cava, Champagne)"
_CHIPS = "Chips, Nuts & Aperitif"
_CHOCOLATE = "Chocolate & Sweets (Biscuits)"
_WASTE_BAGS = "Official Waste Bags (PMD/Rest)"
_CLEANING = "Cleaning & Paper Goods"
_PHARMACY = "Pharmacy & Hygiene"
_BABY = "Baby & Kids"
_PET = "Pet Supplies"
_TOBACCO = "Tobacco"
_LOTTERY = "Lottery & Scratch Cards"
_PROMOS = "Promos & Discounts"
_DEPOSITS = "Deposits (Statiegeld/Vidange)"
_OTHER = "Other"


# Categories that represent non-product line items (discounts, refunds, deposit returns).
# Excluded from pie chart analytics and not selectable for budget allocation.
EXCLUDED_CATEGORIES: frozenset = frozenset({
    _PROMOS,
    _DEPOSITS,
})


# ============================================================
# GRANULAR CATEGORIES (~200 entries)
# ============================================================

GRANULAR_CATEGORIES: Dict[str, str] = {
    # ===================
    # ALCOHOL
    # ===================
    "Beer Pils": _ALCOHOL,
    "Beer Abbey Trappist": _ALCOHOL,
    "Beer Special": _ALCOHOL,
    "Beer White Fruit": _ALCOHOL,
    "Beer Non-Alcoholic": _SODA,  # Non-alcoholic
    "Cider": _ALCOHOL,
    "Wine Red": _ALCOHOL,
    "Wine White": _ALCOHOL,
    "Wine Rosé": _ALCOHOL,
    "Wine Sparkling": _ALCOHOL,
    "Spirits Whisky": _ALCOHOL,
    "Spirits Gin": _ALCOHOL,
    "Spirits Vodka": _ALCOHOL,
    "Spirits Rum": _ALCOHOL,
    "Spirits Liqueur": _ALCOHOL,
    "Aperitif": _ALCOHOL,

    # ===================
    # DRINKS
    # ===================
    "Cola": _SODA,
    "Lemonade & Soda": _SODA,
    "Energy Drinks": _SODA,
    "Ice Tea": _SODA,
    "Fruit Juice": _SODA,
    "Vegetable Juice": _SODA,
    "Smoothies": _SODA,
    "Syrup": _SODA,
    "Water Still": _WATER,
    "Water Sparkling": _WATER,
    "Water Flavored": _WATER,

    # ===================
    # HOT BEVERAGES
    # ===================
    "Coffee Beans Ground": _COFFEE,
    "Coffee Capsules": _COFFEE,
    "Coffee Instant": _COFFEE,
    "Tea": _COFFEE,
    "Hot Chocolate": _COFFEE,

    # ===================
    # DAIRY, EGGS & CHEESE
    # ===================
    "Plant Milk": _DAIRY,
    "Milk Fresh": _DAIRY,
    "Milk Long Life": _DAIRY,
    "Cream": _DAIRY,
    "Yoghurt Natural": _DAIRY,
    "Yoghurt Fruit": _DAIRY,
    "Yoghurt Drinks": _DAIRY,
    "Skyr & Quark": _DAIRY,
    "Pudding & Desserts": _DAIRY,
    "Butter": _DAIRY,
    "Margarine": _DAIRY,
    "Cooking Fat": _DAIRY,
    "Cheese Hard": _DAIRY,
    "Cheese Soft": _DAIRY,
    "Cheese Blue": _DAIRY,
    "Cheese Fresh": _DAIRY,
    "Cheese Spread": _DAIRY,
    "Cheese Sliced": _DAIRY,
    "Cheese Grated": _DAIRY,
    "Cheese Belgian": _DAIRY,
    "Eggs": _DAIRY,

    # ===================
    # MEAT & POULTRY (RAW)
    # ===================
    "Beef": _MEAT_RAW,
    "Pork": _MEAT_RAW,
    "Chicken": _MEAT_RAW,
    "Turkey": _MEAT_RAW,
    "Lamb": _MEAT_RAW,
    "Minced Meat": _MEAT_RAW,
    "Meat Preparations": _MEAT_RAW,
    "Offal": _MEAT_RAW,

    # ===================
    # CHARCUTERIE & SALADS (PREPARÉ/DELI)
    # ===================
    "Ham Cooked": _CHARCUTERIE,
    "Ham Dry": _CHARCUTERIE,
    "Salami & Sausage": _CHARCUTERIE,
    "Pâté & Terrine": _CHARCUTERIE,
    "Bacon & Lardons": _CHARCUTERIE,
    "Chicken Turkey Deli": _CHARCUTERIE,
    "Vegetarian Deli": _CHARCUTERIE,
    "Meals Salads": _CHARCUTERIE,
    "Sandwiches": _CHARCUTERIE,
    "Sushi": _CHARCUTERIE,
    "Hummus & Dips": _CHARCUTERIE,

    # ===================
    # FISH & SEAFOOD
    # ===================
    "Fish Fresh": _FISH,
    "Fish Smoked": _FISH,
    "Fish Frozen": _FISH,
    "Shellfish": _FISH,
    "Canned Fish": _FISH,
    "Surimi": _FISH,

    # ===================
    # FRUITS
    # ===================
    "Fruit Apples Pears": _FRUITS,
    "Fruit Citrus": _FRUITS,
    "Fruit Bananas": _FRUITS,
    "Fruit Berries": _FRUITS,
    "Fruit Stone": _FRUITS,
    "Fruit Grapes": _FRUITS,
    "Fruit Melons": _FRUITS,
    "Fruit Tropical": _FRUITS,
    "Fruit Dried": _FRUITS,
    "Nuts": _FRUITS,

    # ===================
    # VEGETABLES
    # ===================
    "Tomatoes": _VEGETABLES,
    "Salad & Leafy Greens": _VEGETABLES,
    "Cucumber & Peppers": _VEGETABLES,
    "Onions & Garlic": _VEGETABLES,
    "Carrots & Root Veg": _VEGETABLES,
    "Potatoes": _VEGETABLES,
    "Cabbage & Broccoli": _VEGETABLES,
    "Beans & Peas": _VEGETABLES,
    "Mushrooms": _VEGETABLES,
    "Zucchini & Eggplant": _VEGETABLES,
    "Corn": _VEGETABLES,
    "Fresh Herbs": _VEGETABLES,
    "Prepared Vegetables": _VEGETABLES,

    # ===================
    # BAKERY (BREAD, PISTOLETS)
    # ===================
    "Bread Fresh": _BAKERY,
    "Bread Sliced": _BAKERY,
    "Bread Specialty": _BAKERY,
    "Wraps & Pita": _BAKERY,
    "Crackers": _BAKERY,

    # ===================
    # PASTRIES & KOFFIEKOEKEN
    # ===================
    "Croissants & Pastries": _PASTRIES,
    "Cakes & Tarts": _PASTRIES,
    "Waffles": _PASTRIES,

    # ===================
    # GRAINS, PASTA & POTATOES
    # ===================
    "Pasta Dry": _GRAINS,
    "Pasta Fresh": _GRAINS,
    "Rice": _GRAINS,
    "Noodles Asian": _GRAINS,
    "Couscous & Bulgur": _GRAINS,
    "Grains & Legumes": _GRAINS,

    # ===================
    # CANNED & JARRED GOODS
    # ===================
    "Canned Tomatoes": _CANNED,
    "Canned Vegetables": _CANNED,
    "Canned Beans": _CANNED,
    "Canned Fruits": _CANNED,
    "Pickles & Olives": _CANNED,
    "Jarred Antipasti": _CANNED,
    "Soup Canned": _CANNED,
    "Soup Carton Fresh": _CANNED,
    "Soup Instant": _CANNED,

    # ===================
    # SAUCES, MAYO & CONDIMENTS
    # ===================
    "Pasta Sauce": _SAUCES,
    "Tomato Sauce & Ketchup": _SAUCES,
    "Mayonnaise": _SAUCES,
    "Mustard": _SAUCES,
    "Soy & Asian Sauce": _SAUCES,
    "BBQ Sauce": _SAUCES,
    "Salad Dressing": _SAUCES,
    "Vinegar": _SAUCES,
    "Olive Oil": _SAUCES,
    "Cooking Oil": _SAUCES,
    "Salt Pepper & Spices": _SAUCES,
    "Stock & Bouillon": _SAUCES,
    "Dried Herbs": _SAUCES,

    # ===================
    # BREAKFAST & CEREAL (CHOCO/JAM)
    # ===================
    "Cereals": _BREAKFAST,
    "Oatmeal": _BREAKFAST,
    "Spreads Chocolate": _BREAKFAST,
    "Spreads Jam": _BREAKFAST,
    "Spreads Honey": _BREAKFAST,
    "Spreads Peanut Nut": _BREAKFAST,
    "Spreads Savory": _BREAKFAST,

    # ===================
    # BAKING & FLOUR
    # ===================
    "Flour": _BAKING,
    "Sugar": _BAKING,
    "Baking Ingredients": _BAKING,
    "Baking Decorations": _BAKING,
    "Chocolate Baking": _BAKING,

    # ===================
    # CHIPS, NUTS & APERITIF (SNACKS)
    # ===================
    "Chips": _CHIPS,
    "Nuts Snack": _CHIPS,
    "Crackers Snack": _CHIPS,
    "Popcorn": _CHIPS,
    "Dried Meat Snack": _CHIPS,
    "Cookies & Biscuits": _CHOCOLATE,
    "Protein Bars": _CHIPS,

    # ===================
    # CHOCOLATE & SWEETS (BISCUITS)
    # ===================
    "Chocolate Bars": _CHOCOLATE,
    "Chocolate Pralines": _CHOCOLATE,
    "Candy": _CHOCOLATE,
    "Licorice": _CHOCOLATE,
    "Gum & Mints": _CHOCOLATE,
    "Marshmallows": _CHOCOLATE,

    # ===================
    # FROZEN INGREDIENTS (VEG/FRUIT)
    # ===================
    "Frozen Vegetables": _FROZEN_INGR,
    "Frozen Fish": _FROZEN_INGR,
    "Frozen Meat": _FROZEN_INGR,
    "Frozen Bread": _FROZEN_INGR,
    "Frozen Fruits": _FROZEN_INGR,

    # ===================
    # FRIES & SNACKS (FRITUUR AT HOME)
    # ===================
    "Frozen Fries": _FRIES,
    "Frozen Snacks": _FRIES,
    "Ice Cream": _FROZEN_INGR,
    "Frozen Desserts": _FROZEN_INGR,

    # ===================
    # READY MEALS & PIZZA
    # ===================
    "Frozen Pizza": _READY_MEALS,
    "Frozen Meals": _READY_MEALS,
    "Meals Fresh": _READY_MEALS,
    "Pizza Fresh": _READY_MEALS,
    "Meat Substitute": _READY_MEALS,
    "Vegetarian Meals": _READY_MEALS,
    "Vegan Cheese Dairy": _DAIRY,
    "Asian Food": _READY_MEALS,
    "Mexican Food": _READY_MEALS,
    "Italian Specialty": _READY_MEALS,
    "Middle Eastern": _READY_MEALS,

    # ===================
    # SPORTS NUTRITION
    # ===================
    "Protein Shakes": _DAIRY,
    "Protein Desserts": _DAIRY,

    # ===================
    # BABY & KIDS
    # ===================
    "Baby Milk": _BABY,
    "Baby Food": _BABY,
    "Baby Snacks": _BABY,
    "Diapers": _BABY,
    "Baby Care": _BABY,

    # ===================
    # HOUSEHOLD - WASTE BAGS
    # ===================
    "Trash Bags": _WASTE_BAGS,

    # ===================
    # HOUSEHOLD - CLEANING & PAPER
    # ===================
    "Cleaning All-Purpose": _CLEANING,
    "Cleaning Kitchen": _CLEANING,
    "Cleaning Bathroom": _CLEANING,
    "Cleaning Floor": _CLEANING,
    "Cleaning Glass": _CLEANING,
    "Cleaning WC": _CLEANING,
    "Cleaning Tools": _CLEANING,
    "Laundry Detergent": _CLEANING,
    "Laundry Softener": _CLEANING,
    "Laundry Stain Remover": _CLEANING,
    "Laundry Ironing": _CLEANING,
    "Toilet Paper": _CLEANING,
    "Kitchen Paper": _CLEANING,
    "Tissues": _CLEANING,
    "Napkins": _CLEANING,
    "Batteries": _OTHER,
    "Lightbulbs": _OTHER,
    "Kitchen Accessories": _CLEANING,
    "Party Supplies": _OTHER,
    "Flowers & Plants": _OTHER,

    # ===================
    # PERSONAL CARE / PHARMACY & HYGIENE
    # ===================
    "Shower Gel": _PHARMACY,
    "Soap": _PHARMACY,
    "Deodorant": _PHARMACY,
    "Body Lotion": _PHARMACY,
    "Sunscreen": _PHARMACY,
    "Shampoo": _PHARMACY,
    "Conditioner": _PHARMACY,
    "Hair Styling": _PHARMACY,
    "Hair Color": _PHARMACY,
    "Face Care": _PHARMACY,
    "Toothpaste": _PHARMACY,
    "Toothbrush": _PHARMACY,
    "Mouthwash": _PHARMACY,
    "Shaving": _PHARMACY,
    "Feminine Hygiene": _PHARMACY,
    "Contraception": _PHARMACY,
    "First Aid": _PHARMACY,
    "Vitamins & Supplements": _PHARMACY,
    "Pain Relief": _PHARMACY,

    # ===================
    # PET SUPPLIES
    # ===================
    "Pet Food Dog": _PET,
    "Pet Food Cat": _PET,
    "Pet Treats": _PET,
    "Pet Litter": _PET,
    "Pet Care": _PET,

    # ===================
    # TOBACCO
    # ===================
    "Tobacco": _TOBACCO,

    # ===================
    # LOTTERY & SCRATCH CARDS
    # ===================
    "Lottery & Scratch Cards": _LOTTERY,

    # ===================
    # PROMOS & DISCOUNTS
    # ===================
    "Discount": _PROMOS,
    "Coupon": _PROMOS,
    "Loyalty Discount": _PROMOS,
    "Promotional Offer": _PROMOS,
    "Multi-Buy Deal": _PROMOS,

    # ===================
    # DEPOSITS (STATIEGELD/VIDANGE)
    # ===================
    "Bottle Deposit": _DEPOSITS,
    "Can Deposit": _DEPOSITS,
    "Crate Deposit": _DEPOSITS,
    "Deposit Refund": _DEPOSITS,

    # ===================
    # OTHER
    # ===================
    "Other": _OTHER,
}


# ============================================================
# DERIVED / PRE-COMPUTED LOOKUPS (built at module load time)
# ============================================================

_CATEGORY_LOOKUP: Dict[str, CategoryInfo] = {}
_LOWER_LOOKUP: Dict[str, str] = {}
_DISPLAY_LOOKUP: Dict[str, str] = {}  # display name → internal name
_ALL_CATEGORIES: List[str] = []


def _build_lookups() -> None:
    """Build all lookup tables from _HIERARCHY at module load time."""
    for group_name, categories in _HIERARCHY.items():
        group_color = GROUP_COLORS[group_name]
        group_icon = GROUP_ICONS[group_name]
        for cat_name, display_name in categories:
            info = CategoryInfo(
                name=cat_name,
                display_name=display_name,
                group=group_name,
                color_hex=group_color,
                icon=group_icon,
                category_icon=CATEGORY_ICONS.get(cat_name, "tag"),
                category_color_hex=CATEGORY_COLORS.get(cat_name, group_color),
            )
            _CATEGORY_LOOKUP[cat_name] = info
            _LOWER_LOOKUP[cat_name.lower()] = cat_name
            _DISPLAY_LOOKUP[display_name] = cat_name
            _DISPLAY_LOOKUP[display_name.lower()] = cat_name
            _ALL_CATEGORIES.append(cat_name)


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
    return GRANULAR_CATEGORIES.get(granular, _OTHER)


def get_all_granular_categories() -> List[str]:
    """Get list of all valid granular categories."""
    return list(GRANULAR_CATEGORIES.keys())


def validate_granular_category(granular: str) -> bool:
    """Check if a granular category is valid."""
    return granular in GRANULAR_CATEGORIES


# ============================================================
# PUBLIC API - Parent category functions (replaces CategoryRegistry)
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
    for group_name, categories in _HIERARCHY.items():
        cat_list = []
        for cat_name, display_name in categories:
            cat_list.append({
                "name": cat_name,
                "display_name": display_name,
                "sub_categories": [cat_name],
                "icon": CATEGORY_ICONS.get(cat_name, "tag"),
                "color_hex": CATEGORY_COLORS.get(cat_name, GROUP_COLORS[group_name]),
                "budgetable": cat_name not in EXCLUDED_CATEGORIES,
            })
        groups.append({
            "name": group_name,
            "icon": GROUP_ICONS[group_name],
            "color_hex": GROUP_COLORS[group_name],
            "categories": cat_list,
        })
    return {"groups": groups}

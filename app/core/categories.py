"""
Category definitions — single source of truth for the entire app.

Three-level hierarchy (ECR Total Store Taxonomy):
  Department/Group (5)  →  Macro-Category / Parent (22)  →  Granular (~120)

Everything is defined once in _TREE below. All lookup dicts and constants
are derived from it at module load time.

Supports English ('en'), Dutch ('nl'), and French ('fr').
Features dual-display names: b2b_display (FMCG Dashboard) and b2c_display (iOS App).
"""

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, List, Optional


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass(frozen=True)
class CategoryInfo:
    """Full metadata for a parent category."""
    name: str                       # Internal DB name (e.g., "Sweet Groceries")
    b2b_display: Dict[str, str]     # FMCG Dashboard names (e.g., "Épicerie Sucrée")
    b2c_display: Dict[str, str]     # iOS App User names (e.g., "Snacks & Douceurs")
    group: Dict[str, str]           # Multi-lingual group names
    group_id: str                   # Internal group ID
    color_hex: str                  # Group color (hex)
    icon: str                       # Group icon (SF Symbol)
    category_icon: str              # Per-category icon (Phosphor)
    category_color_hex: str         # Per-category color (hex)
    is_budgetable: bool             # Whether it is included in analytics


# ============================================================
# SINGLE SOURCE OF TRUTH
# ============================================================

_TREE = [

    # ── 1. Ambient Food ──────────────────────────────────────
    {
        "group_id": "Ambient Food",
        "group": {"en": "Pantry", "nl": "Voorraadkast", "fr": "Garde-manger"},
        "color": "#E67E22",
        "icon": "cabinet.fill",
        "categories": [
            {
                "name": "Sweets",
                "b2b_display": {"en": "Sweets", "nl": "Snoep & Koek", "fr": "Confiserie"},
                "b2c_display": {"en": "Sweets", "nl": "Snoep & Koek", "fr": "Confiserie"},
                "icon": "cookie",
                "color": "#D97706",
                "granular": ["Biscuits & Pastries", "Chocolate & Confectionery", "Desserts & Home Baking"],
            },
            {
                "name": "Breakfast",
                "b2b_display": {"en": "Breakfast", "nl": "Ontbijt", "fr": "Petit-déjeuner"},
                "b2c_display": {"en": "Breakfast", "nl": "Ontbijt", "fr": "Petit-déjeuner"},
                "icon": "coffee",
                "color": "#F59E0B",
                "granular": ["Breakfast & Cereals", "Sweet Spreads & Honey"],
            },
            {
                "name": "Snacks",
                "b2b_display": {"en": "Snacks", "nl": "Snacks", "fr": "Snacks"},
                "b2c_display": {"en": "Snacks", "nl": "Snacks", "fr": "Snacks"},
                "icon": "chips",
                "color": "#EF4444",
                "granular": ["Salty Snacks & Nuts"],
            },
            {
                "name": "Savory Groceries",
                "b2b_display": {"en": "Savory Groceries", "nl": "Zoute Kruidenierswaren", "fr": "Épicerie Salée"},
                "b2c_display": {"en": "Dry Goods & Staples", "nl": "Droge Voeding & Basisproducten", "fr": "Épicerie Sèche & Essentiels"},
                "icon": "pepper",
                "color": "#EA580C",
                "granular": ["Condiments & Sauces", "Soups & Bouillons", "Canned & Jarred Goods", "Staples Pasta Rice", "Oils & Vinegars"],
            },
        ],
    },

    # ── 2. Beverages ─────────────────────────────────────────
    {
        "group_id": "Beverages",
        "group": {"en": "Beverages", "nl": "Dranken", "fr": "Boissons"},
        "color": "#E74C3C",
        "icon": "mug.fill",
        "categories": [
            {
                "name": "Water & Juices",
                "b2b_display": {"en": "Water & Juices", "nl": "Water & Sappen", "fr": "Eaux & Jus"},
                "b2c_display": {"en": "Water & Juices", "nl": "Water & Sappen", "fr": "Eaux & Jus"},
                "icon": "drop",
                "color": "#38BDF8",
                "granular": ["Still Water", "Sparkling Water", "Fruit Juices", "Smoothies & Fresh Juices", "Syrups & Cordials"],
            },
            {
                "name": "Sodas & Energy Drinks",
                "b2b_display": {"en": "Sodas & Energy Drinks", "nl": "Frisdranken & Energiedranken", "fr": "Sodas & Boissons Énergisantes"},
                "b2c_display": {"en": "Sodas & Energy Drinks", "nl": "Frisdrank & Energy Drinks", "fr": "Sodas & Energy Drinks"},
                "icon": "lightning",
                "color": "#F43F5E",
                "granular": ["Colas", "Fruit Sodas & Lemonades", "Iced Teas", "Energy Drinks", "Sports Drinks"],
            },
            {
                "name": "Coffee & Tea",
                "b2b_display": {"en": "Coffee & Tea", "nl": "Koffie & Thee", "fr": "Café & Thé"},
                "b2c_display": {"en": "Coffee & Tea", "nl": "Koffie & Thee", "fr": "Café & Thé"},
                "icon": "coffee",
                "color": "#78350F",
                "granular": ["Coffee Beans & Ground", "Coffee Pods & Capsules", "Instant Coffee", "Tea Bags & Loose Tea"],
            },
        ],
    },

    # ── 3. Alcohol ──────────────────────────────────────────
    {
        "group_id": "Alcohol",
        "group": {"en": "Alcohol", "nl": "Alcohol", "fr": "Alcool"},
        "color": "#9F1239",
        "icon": "wine",
        "categories": [
            {
                "name": "Alcohol",
                "b2b_display": {"en": "Alcohol", "nl": "Alcohol", "fr": "Alcool"},
                "b2c_display": {"en": "Alcohol", "nl": "Alcohol", "fr": "Alcool"},
                "icon": "wine",
                "color": "#9F1239",
                "granular": [
                    "Pilsners & Lagers", "Specialty & Abbey Beers", "Fruit Beers & Geuze",
                    "Non-Alcoholic Beers (0.0%)", "Ciders",
                    "Red Wine", "White Wine", "Rosé Wine", "Champagne & Sparkling Wine",
                    "Non-Alcoholic Wine",
                    "Gin, Vodka & White Spirits", "Whisky, Rum & Dark Spirits",
                    "Liqueurs & Digestifs", "Aperitifs & Ready-to-Drink",
                ],
            },
        ],
    },

    # ── 4. Fresh Food ──────────────────────────────────────
    {
        "group_id": "Fresh & Chilled",
        "group": {"en": "Fresh Food", "nl": "Verse Producten", "fr": "Produits Frais"},
        "color": "#2ECC71",
        "icon": "leaf.fill",
        "categories": [
            {
                "name": "Dairy & Eggs",
                "b2b_display": {"en": "Dairy & Eggs", "nl": "Zuivel & Eieren", "fr": "Crémerie & Œufs"},
                "b2c_display": {"en": "Dairy & Eggs", "nl": "Zuivel & Eieren", "fr": "Laitage & Œufs"},
                "icon": "egg",
                "color": "#FACC15",
                "granular": [
                    "Fresh Milk", "Long Life Milk", "Plant Milk", "Cream",
                    "Cheese Hard", "Cheese Soft & Blue", "Cheese Fresh & Spread", "Cheese Sliced & Grated",
                    "Yoghurt Plain", "Yoghurt Fruit & Drinks", "Skyr & Quark", "Chilled Desserts",
                    "Butter & Margarine",
                    "Eggs",
                ],
            },
            {
                "name": "Deli & Convenience",
                "b2b_display": {"en": "Deli & Convenience", "nl": "Traiteur & Kant-en-klaar", "fr": "Traiteur & Plats Préparés"},
                "b2c_display": {"en": "Deli & Ready Meals", "nl": "Traiteur & Maaltijden", "fr": "Traiteur & Plats"},
                "icon": "bowl-food",
                "color": "#F87171",
                "granular": ["Charcuterie", "Chilled Ready Meals", "Plant-Based Meat Alternatives", "Fresh Tapas & Salads"],
            },
            {
                "name": "Meat & Poultry",
                "b2b_display": {"en": "Meat & Poultry", "nl": "Vlees & Gevogelte", "fr": "Boucherie & Volaille"},
                "b2c_display": {"en": "Meat & Poultry", "nl": "Vlees & Kip", "fr": "Viande & Volaille"},
                "icon": "meat",
                "color": "#FB923C",
                "granular": ["Beef Veal Pork", "Poultry & Game"],
            },
            {
                "name": "Seafood",
                "b2b_display": {"en": "Seafood", "nl": "Vis & Schaaldieren", "fr": "Poissonnerie"},
                "b2c_display": {"en": "Fish & Seafood", "nl": "Vis & Zeevruchten", "fr": "Poisson & Fruits de Mer"},
                "icon": "fish-simple",
                "color": "#22D3EE",
                "granular": ["Fresh Fish", "Shellfish & Crustaceans"],
            },
            {
                "name": "Fruit & Vegetables",
                "b2b_display": {"en": "Fruit & Vegetables", "nl": "Groenten & Fruit", "fr": "Fruits & Légumes"},
                "b2c_display": {"en": "Fruit & Vegetables", "nl": "Groenten & Fruit", "fr": "Fruits & Légumes"},
                "icon": "carrot",
                "color": "#16A34A",
                "granular": [
                    "Apples & Pears", "Citrus Fruit", "Bananas", "Berries", "Stone & Tropical Fruit", "Dried Fruit & Nuts",
                    "Tomatoes & Peppers", "Salad & Leafy Greens", "Root Vegetables & Potatoes", "Cabbage & Broccoli", "Mushrooms & Other Vegetables", "Fresh Herbs",
                ],
            },
            {
                "name": "Fresh Bakery",
                "b2b_display": {"en": "Fresh Bakery", "nl": "Verse Bakkerij", "fr": "Boulangerie Fraîche"},
                "b2c_display": {"en": "Bakery", "nl": "Bakkerij", "fr": "Boulangerie"},
                "icon": "bread",
                "color": "#F59E0B",
                "granular": ["Daily Bread", "Viennoiserie & Patisserie"],
            },
        ],
    },

    # ── 5. Frozen Food ───────────────────────────────────────
    {
        "group_id": "Frozen Food",
        "group": {"en": "Frozen", "nl": "Diepvries", "fr": "Surgelés"},
        "color": "#3498DB",
        "icon": "snowflake",
        "categories": [
            {
                "name": "Frozen",
                "b2b_display": {"en": "Frozen", "nl": "Diepvries", "fr": "Surgelés"},
                "b2c_display": {"en": "Frozen", "nl": "Diepvries", "fr": "Surgelés"},
                "icon": "snowflake.circle",
                "color": "#3498DB",
                "granular": ["Frozen Potato Products", "Frozen Vegetables & Herbs", "Frozen Meat & Seafood", "Frozen Ready Meals & Pizzas", "Ice Cream", "Frozen Desserts & Pastries"],
            },
        ],
    },

    # ── 6. Baby & Kids ──────────────────────────────────────
    {
        "group_id": "Baby & Kids",
        "group": {"en": "Baby & Kids", "nl": "Baby & Kids", "fr": "Bébé & Enfants"},
        "color": "#F472B6",
        "icon": "figure.and.child.holdinghands",
        "categories": [
            {
                "name": "Baby Food & Care",
                "b2b_display": {"en": "Baby Food", "nl": "Babyvoeding", "fr": "Alimentation Bébé"},
                "b2c_display": {"en": "Baby Food", "nl": "Babyvoeding", "fr": "Alimentation Bébé"},
                "icon": "baby-carriage",
                "color": "#F472B6",
                "granular": ["Baby Formula & Milk", "Baby Meals & Purees", "Baby Snacks & Biscuits", "Baby Care"],
            },
        ],
    },

    # ── 7. Tobacco ───────────────────────────────────────────
    {
        "group_id": "Tobacco",
        "group": {"en": "Tobacco", "nl": "Tabak", "fr": "Tabac"},
        "color": "#1F2937",
        "icon": "smoke.fill",
        "categories": [
            {
                "name": "Tobacco & Vaping",
                "b2b_display": {"en": "Tobacco & Vaping", "nl": "Tabak & Vaping", "fr": "Tabac & Vapotage"},
                "b2c_display": {"en": "Tobacco", "nl": "Tabak", "fr": "Tabac"},
                "icon": "prohibit",
                "color": "#1F2937",
                "granular": ["Cigarettes & Rolling Tobacco", "Cigars & Cigarillos", "E-Cigarettes & Vapes", "Smoking Accessories"],
            },
        ],
    },

    # ── 8. Non-Food & Near-Food ──────────────────────────────
    {
        "group_id": "Non-Food",
        "group": {"en": "Household & Care", "nl": "Verzorging & Huis", "fr": "Maison & Soins"},
        "color": "#8E44AD",
        "icon": "bubbles.and.sparkles.fill",
        "categories": [
            {
                "name": "Personal Care",
                "b2b_display": {"en": "Personal Care", "nl": "Persoonlijke Verzorging", "fr": "Parfumerie & Hygiène"},
                "b2c_display": {"en": "Personal Care", "nl": "Verzorging", "fr": "Soins & Beauté"},
                "icon": "hand-heart",
                "color": "#1ABC9C",
                "granular": [
                    "Shampoo & Conditioner", "Hair Styling & Color",
                    "Toothpaste & Toothbrush", "Mouthwash",
                    "Shower & Bath", "Deodorant", "Body & Face Care", "Sunscreen",
                    "Feminine Hygiene",
                ],
            },
            {
                "name": "Home Care",
                "b2b_display": {"en": "Home Care", "nl": "Onderhoud", "fr": "Entretien"},
                "b2c_display": {"en": "Household & Cleaning", "nl": "Huishouden & Schoonmaak", "fr": "Maison & Entretien"},
                "icon": "toilet-paper",
                "color": "#A855F7",
                "granular": ["Laundry Care", "Dishwashing", "Surface Care", "Paper Products & Waste Bags"],
            },
            {
                "name": "Pet Care",
                "b2b_display": {"en": "Pet Care", "nl": "Dierenartikelen", "fr": "Animalerie"},
                "b2c_display": {"en": "Pets", "nl": "Huisdieren", "fr": "Animaux"},
                "icon": "paw-print",
                "color": "#64748B",
                "granular": ["Dog Care", "Cat Care", "Other Pet Supplies"],
            },
            {
                "name": "General Merchandise",
                "b2b_display": {"en": "General Merchandise", "nl": "Bazar & Non-Food", "fr": "Bazar & Divers"},
                "b2c_display": {"en": "Home & Extras", "nl": "Wonen & Extra", "fr": "Maison & Divers"},
                "icon": "squares-four",
                "color": "#94A3B8",
                "granular": ["Household & Kitchenware", "Stationery & Media"],
            },
            {
                "name": "Lottery & Scratch Cards",
                "b2b_display": {"en": "Lottery & Scratch Cards", "nl": "Loterij & Krasloten", "fr": "Loterie & Jeux à gratter"},
                "b2c_display": {"en": "Lottery", "nl": "Loterij", "fr": "Loterie"},
                "icon": "ticket",
                "color": "#10B981",
                "granular": ["Lottery & Scratch Cards"],
            },
            {
                "name": "System Excluded",
                "b2b_display": {"en": "Discounts & Deposits", "nl": "Kortingen & Statiegeld", "fr": "Réductions & Consignes"},
                "b2c_display": {"en": "Discounts & Deposits", "nl": "Korting & Statiegeld", "fr": "Promo & Consignes"},
                "icon": "recycle",
                "color": "#94A3B8",
                "excluded": True,
                "granular": ["Discount", "Bottle Deposit", "Refund"],
            },
        ],
    },
]


# ============================================================
# DERIVED LOOKUPS (built once at module load time)
# ============================================================

_CATEGORY_LOOKUP: Dict[str, CategoryInfo] = {}
_LOWER_LOOKUP: Dict[str, str] = {}
_DISPLAY_LOOKUP: Dict[str, str] = {}
_ALL_CATEGORIES: List[str] = []
GRANULAR_CATEGORIES: Dict[str, str] = {}
EXCLUDED_CATEGORIES: frozenset[str]


def _build_lookups() -> None:
    excluded = set()

    for group in _TREE:
        for cat in group["categories"]:
            cat_name = cat["name"]
            is_excluded = cat.get("excluded", False)

            if is_excluded:
                excluded.add(cat_name)

            for granular in cat.get("granular", []):
                GRANULAR_CATEGORIES[granular] = cat_name

            info = CategoryInfo(
                name=cat_name,
                b2b_display=cat["b2b_display"],
                b2c_display=cat["b2c_display"],
                group=group["group"],
                group_id=group["group_id"],
                color_hex=group["color"],
                icon=group["icon"],
                category_icon=cat["icon"],
                category_color_hex=cat["color"],
                is_budgetable=not is_excluded
            )

            _CATEGORY_LOOKUP[cat_name] = info
            _LOWER_LOOKUP[cat_name.lower()] = cat_name

            # Safely index translations without KeyError risks
            for display_dict in [cat.get("b2b_display", {}), cat.get("b2c_display", {})]:
                for lang, text in display_dict.items():
                    _DISPLAY_LOOKUP[text] = cat_name
                    _DISPLAY_LOOKUP[text.lower()] = cat_name

    global EXCLUDED_CATEGORIES
    EXCLUDED_CATEGORIES = frozenset(excluded)

    global _ALL_CATEGORIES
    _ALL_CATEGORIES = list(_CATEGORY_LOOKUP.keys())

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
    """Get parent category for a granular category, defaulting to 'General Merchandise'."""
    return GRANULAR_CATEGORIES.get(granular, "General Merchandise")

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
    """Get full info for a parent category (case-insensitive & multi-lingual)."""
    if category in _CATEGORY_LOOKUP:
        return _CATEGORY_LOOKUP[category]
    if category in _DISPLAY_LOOKUP:
        return _CATEGORY_LOOKUP[_DISPLAY_LOOKUP[category]]

    canonical = _LOWER_LOOKUP.get(category.lower())
    if canonical:
        return _CATEGORY_LOOKUP[canonical]

    lower_display = _DISPLAY_LOOKUP.get(category.lower())
    if lower_display:
        return _CATEGORY_LOOKUP[lower_display]

    return None

def get_display_name(category: str, lang: str = "en", mode: str = "b2c") -> str:
    """Get clean display name for a category. Defaults to English B2C (iOS users)."""
    info = get_category_info(category)
    if not info:
        return category

    display_dict = info.b2c_display if mode == "b2c" else info.b2b_display
    return display_dict.get(lang, display_dict.get("en", category))

def get_group(category: str, lang: str = "en") -> Optional[str]:
    """Get the group name for a category."""
    info = get_category_info(category)
    if not info:
        return None
    return info.group.get(lang, info.group.get("en"))

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
    """Resolve a category string to its internal name (the key stored in the DB)."""
    info = get_category_info(category)
    return info.name if info else None

def is_valid_category(category: str) -> bool:
    """Check if a parent category name is valid (case-insensitive)."""
    return get_category_info(category) is not None

def get_all_categories() -> List[str]:
    """Get all parent category names."""
    return _ALL_CATEGORIES.copy()

def get_all_groups() -> List[str]:
    """Get all group names (returns internal group IDs like 'Ambient Food')."""
    return [group["group_id"] for group in _TREE]

def get_categories_for_group(group_id: str) -> List[str]:
    """Get all category names in a group."""
    for group in _TREE:
        if group["group_id"] == group_id or group_id in group["group"].values():
            return [cat["name"] for cat in group["categories"]]
    return []

def get_category_id(category: str) -> str:
    """Generate a stable UPPER_SNAKE_CASE ID from a category's internal name.
    e.g. "Meat & Poultry" -> "MEAT_POULTRY"
    """
    internal_name = get_internal_name(category) or category
    s = internal_name.upper()
    s = s.replace("(", "").replace(")", "")
    for ch in "&/-,.":
        s = s.replace(ch, "_")
    s = re.sub(r"[\s_]+", "_", s)
    s = s.strip("_")
    return s

def find_closest_match(name: str, threshold: float = 0.6) -> Optional[str]:
    """Find closest matching parent category using fuzzy matching."""
    if is_valid_category(name):
        return get_internal_name(name)

    best_match = None
    best_score = 0.0
    name_lower = name.lower()

    # Match against all known display translations
    for display_str, internal_name in _DISPLAY_LOOKUP.items():
        score = SequenceMatcher(None, name_lower, display_str).ratio()
        if score > best_score and score >= threshold:
            best_score = score
            best_match = internal_name

    return best_match

# ============================================================
# SEARCH SYNONYMS — multilingual term → granular categories
# ============================================================
#
# Powers the promo search bar: a user typing "bier" / "biere" / "beer" must
# resolve to all beer granulars even though "Pilsners & Lagers" doesn't
# contain that word. Two layers feed the lookup:
#
#   1. Auto-derived from _TREE: every meaningful token in any parent's
#      b2c_display / b2b_display (en/nl/fr) and every group's group dict
#      maps to all granulars under that parent/group. Covers the broad case
#      ("kip" → Meat & Poultry granulars, "zuivel" → Dairy & Eggs granulars).
#
#   2. Manually curated _SUB_CLUSTER_SYNONYMS: narrower terms that don't
#      appear in any parent display name but identify a coherent subset of
#      granulars within a parent (e.g. "bier" picks 4 of the 14 alcohol
#      granulars). Lowercase, unaccented keys.

_STOPWORDS: frozenset[str] = frozenset({
    "&", "and", "et", "en", "de", "des", "du", "la", "le", "les", "à", "a",
    "of", "the", "to", "for", "with", "y", "i",
})

# Tokens that auto-derivation should NOT register, because they're either
# generic ("food", "care") or ambiguous across very different parents.
# (Sub-cluster overrides ignore this list.)
_AUTODERIVE_BLOCKLIST: frozenset[str] = frozenset({
    "food", "fresh", "household", "general", "system", "merchandise",
    "kids", "extras", "extra", "pantry", "groceries", "epicerie",
    "épicerie", "garde", "manger", "produits", "verse",
})

_SUB_CLUSTER_SYNONYMS: dict[str, list[str]] = {
    # ── Beers (parent is the broad "Alcohol") ──
    "bier":   ["Pilsners & Lagers", "Specialty & Abbey Beers",
               "Non-Alcoholic Beers (0.0%)", "Fruit Beers & Geuze"],
    "biere":  ["Pilsners & Lagers", "Specialty & Abbey Beers",
               "Non-Alcoholic Beers (0.0%)", "Fruit Beers & Geuze"],
    "beer":   ["Pilsners & Lagers", "Specialty & Abbey Beers",
               "Non-Alcoholic Beers (0.0%)", "Fruit Beers & Geuze"],
    "pils":   ["Pilsners & Lagers"],
    "lager":  ["Pilsners & Lagers"],
    "trappist": ["Specialty & Abbey Beers"],
    "abdij":  ["Specialty & Abbey Beers"],
    "abbaye": ["Specialty & Abbey Beers"],
    # ── Wines ──
    "wijn":   ["Red Wine", "White Wine", "Rosé Wine",
               "Champagne & Sparkling Wine", "Non-Alcoholic Wine"],
    "vin":    ["Red Wine", "White Wine", "Rosé Wine",
               "Champagne & Sparkling Wine", "Non-Alcoholic Wine"],
    "wine":   ["Red Wine", "White Wine", "Rosé Wine",
               "Champagne & Sparkling Wine", "Non-Alcoholic Wine"],
    "champagne": ["Champagne & Sparkling Wine"],
    "bubbels":   ["Champagne & Sparkling Wine"],
    "cava":   ["Champagne & Sparkling Wine"],
    "prosecco": ["Champagne & Sparkling Wine"],
    # ── Spirits ──
    "sterke drank": ["Gin, Vodka & White Spirits", "Whisky, Rum & Dark Spirits",
                     "Liqueurs & Digestifs", "Aperitifs & Ready-to-Drink"],
    "spirits": ["Gin, Vodka & White Spirits", "Whisky, Rum & Dark Spirits",
                "Liqueurs & Digestifs", "Aperitifs & Ready-to-Drink"],
    "spiritueux": ["Gin, Vodka & White Spirits", "Whisky, Rum & Dark Spirits",
                   "Liqueurs & Digestifs", "Aperitifs & Ready-to-Drink"],
    "gin":    ["Gin, Vodka & White Spirits"],
    "vodka":  ["Gin, Vodka & White Spirits"],
    "whisky": ["Whisky, Rum & Dark Spirits"],
    "whiskey": ["Whisky, Rum & Dark Spirits"],
    "rum":    ["Whisky, Rum & Dark Spirits"],
    "porto":  ["Liqueurs & Digestifs"],
    "likeur": ["Liqueurs & Digestifs"],
    "liqueur": ["Liqueurs & Digestifs"],
    "aperitief": ["Aperitifs & Ready-to-Drink"],
    "aperitif":  ["Aperitifs & Ready-to-Drink"],
    "apero":  ["Aperitifs & Ready-to-Drink"],
    "cocktail": ["Aperitifs & Ready-to-Drink"],
    # ── Soft drinks ──
    "frisdrank": ["Colas", "Fruit Sodas & Lemonades", "Iced Teas",
                  "Energy Drinks", "Sports Drinks"],
    "soft drink": ["Colas", "Fruit Sodas & Lemonades", "Iced Teas",
                   "Energy Drinks", "Sports Drinks"],
    "soda":   ["Colas", "Fruit Sodas & Lemonades"],
    "sodas":  ["Colas", "Fruit Sodas & Lemonades"],
    "cola":   ["Colas"],
    "coca":   ["Colas"],
    "limonade": ["Fruit Sodas & Lemonades"],
    "lemonade": ["Fruit Sodas & Lemonades"],
    "ice tea": ["Iced Teas"],
    "ijsthee": ["Iced Teas"],
    "energy drink": ["Energy Drinks"],
    "sportdrank": ["Sports Drinks"],
    # ── Coffee & Tea ──
    "koffie": ["Coffee Beans & Ground", "Coffee Pods & Capsules", "Instant Coffee"],
    "café":   ["Coffee Beans & Ground", "Coffee Pods & Capsules", "Instant Coffee"],
    "cafe":   ["Coffee Beans & Ground", "Coffee Pods & Capsules", "Instant Coffee"],
    "coffee": ["Coffee Beans & Ground", "Coffee Pods & Capsules", "Instant Coffee"],
    "thee":   ["Tea Bags & Loose Tea"],
    "thé":    ["Tea Bags & Loose Tea"],
    "the":    ["Tea Bags & Loose Tea"],
    "tea":    ["Tea Bags & Loose Tea"],
    # ── Water ──
    "water":  ["Still Water", "Sparkling Water"],
    "eau":    ["Still Water", "Sparkling Water"],
    "bruisend": ["Sparkling Water"],
    "petillante": ["Sparkling Water"],
    "plat":   ["Still Water"],
    # ── Juice ──
    "sap":    ["Fruit Juices", "Smoothies & Fresh Juices"],
    "jus":    ["Fruit Juices", "Smoothies & Fresh Juices"],
    "juice":  ["Fruit Juices", "Smoothies & Fresh Juices"],
    "smoothie": ["Smoothies & Fresh Juices"],
    # ── Cheese (split across 4 granulars under Dairy & Eggs) ──
    "kaas":   ["Cheese Hard", "Cheese Soft & Blue",
               "Cheese Fresh & Spread", "Cheese Sliced & Grated"],
    "fromage": ["Cheese Hard", "Cheese Soft & Blue",
                "Cheese Fresh & Spread", "Cheese Sliced & Grated"],
    "cheese": ["Cheese Hard", "Cheese Soft & Blue",
               "Cheese Fresh & Spread", "Cheese Sliced & Grated"],
    # ── Yoghurt / Milk ──
    "yoghurt": ["Yoghurt Plain", "Yoghurt Fruit & Drinks", "Skyr & Quark"],
    "yaourt":  ["Yoghurt Plain", "Yoghurt Fruit & Drinks", "Skyr & Quark"],
    "yogurt":  ["Yoghurt Plain", "Yoghurt Fruit & Drinks", "Skyr & Quark"],
    "skyr":    ["Skyr & Quark"],
    "melk":    ["Fresh Milk", "Long Life Milk", "Plant Milk"],
    "lait":    ["Fresh Milk", "Long Life Milk", "Plant Milk"],
    "milk":    ["Fresh Milk", "Long Life Milk", "Plant Milk"],
    "boter":   ["Butter & Margarine"],
    "beurre":  ["Butter & Margarine"],
    "butter":  ["Butter & Margarine"],
    "ei":      ["Eggs"],
    "eieren":  ["Eggs"],
    "œuf":     ["Eggs"],
    "oeuf":    ["Eggs"],
    "egg":     ["Eggs"],
    "eggs":    ["Eggs"],
    # ── Sweets / Bakery ──
    "chocolade": ["Chocolate & Confectionery"],
    "chocolat":  ["Chocolate & Confectionery"],
    "chocolate": ["Chocolate & Confectionery"],
    "snoep":     ["Chocolate & Confectionery"],
    "bonbon":    ["Chocolate & Confectionery"],
    "koek":      ["Biscuits & Pastries"],
    "biscuit":   ["Biscuits & Pastries"],
    "biscuits":  ["Biscuits & Pastries"],
    "cookies":   ["Biscuits & Pastries"],
    "brood":     ["Daily Bread"],
    "pain":      ["Daily Bread"],
    "bread":     ["Daily Bread"],
    "viennoiserie": ["Viennoiserie & Patisserie"],
    "croissant": ["Viennoiserie & Patisserie"],
    # ── Frozen ──
    "ijs":     ["Ice Cream", "Frozen Desserts & Pastries"],
    "ijsje":   ["Ice Cream", "Frozen Desserts & Pastries"],
    "ijsjes":  ["Ice Cream", "Frozen Desserts & Pastries"],
    "glace":   ["Ice Cream", "Frozen Desserts & Pastries"],
    "ice cream": ["Ice Cream"],
    "pizza":   ["Frozen Ready Meals & Pizzas"],
    "frieten": ["Frozen Potato Products"],
    "frites":  ["Frozen Potato Products"],
    "fries":   ["Frozen Potato Products"],
    # ── Meat / Poultry / Fish (parent display names already cover broad terms) ──
    "vlees":   ["Beef Veal Pork", "Poultry & Game"],
    "viande":  ["Beef Veal Pork", "Poultry & Game"],
    "meat":    ["Beef Veal Pork", "Poultry & Game"],
    "kip":     ["Poultry & Game"],
    "poulet":  ["Poultry & Game"],
    "chicken": ["Poultry & Game"],
    "rund":    ["Beef Veal Pork"],
    "varken":  ["Beef Veal Pork"],
    "porc":    ["Beef Veal Pork"],
    "boeuf":   ["Beef Veal Pork"],
    "beef":    ["Beef Veal Pork"],
    "vis":     ["Fresh Fish", "Frozen Meat & Seafood"],
    "poisson": ["Fresh Fish", "Frozen Meat & Seafood"],
    "fish":    ["Fresh Fish", "Frozen Meat & Seafood"],
    "saumon":  ["Fresh Fish"],
    "zalm":    ["Fresh Fish"],
    "salmon":  ["Fresh Fish"],
    "garnaal": ["Shellfish & Crustaceans"],
    "crevette": ["Shellfish & Crustaceans"],
    "shrimp":  ["Shellfish & Crustaceans"],
    "charcuterie": ["Charcuterie"],
    # ── Fruits & Vegetables ──
    "fruit":    ["Apples & Pears", "Citrus Fruit", "Bananas", "Berries",
                 "Stone & Tropical Fruit", "Dried Fruit & Nuts"],
    "groente":  ["Tomatoes & Peppers", "Salad & Leafy Greens",
                 "Root Vegetables & Potatoes", "Cabbage & Broccoli",
                 "Mushrooms & Other Vegetables", "Fresh Herbs"],
    "groenten": ["Tomatoes & Peppers", "Salad & Leafy Greens",
                 "Root Vegetables & Potatoes", "Cabbage & Broccoli",
                 "Mushrooms & Other Vegetables", "Fresh Herbs"],
    "légume":   ["Tomatoes & Peppers", "Salad & Leafy Greens",
                 "Root Vegetables & Potatoes", "Cabbage & Broccoli",
                 "Mushrooms & Other Vegetables", "Fresh Herbs"],
    "legume":   ["Tomatoes & Peppers", "Salad & Leafy Greens",
                 "Root Vegetables & Potatoes", "Cabbage & Broccoli",
                 "Mushrooms & Other Vegetables", "Fresh Herbs"],
    "appel":    ["Apples & Pears"],
    "pomme":    ["Apples & Pears"],
    "apple":    ["Apples & Pears"],
    "banaan":   ["Bananas"],
    "banane":   ["Bananas"],
    "banana":   ["Bananas"],
    "tomaat":   ["Tomatoes & Peppers"],
    "tomate":   ["Tomatoes & Peppers"],
    "tomato":   ["Tomatoes & Peppers"],
    "patat":    ["Root Vegetables & Potatoes"],
    "aardappel": ["Root Vegetables & Potatoes"],
    "pomme de terre": ["Root Vegetables & Potatoes"],
    "potato":   ["Root Vegetables & Potatoes"],
    "champignon": ["Mushrooms & Other Vegetables"],
    "salade":   ["Salad & Leafy Greens"],
    "sla":      ["Salad & Leafy Greens"],
    # ── Personal & Home Care narrower terms ──
    "shampoo":   ["Shampoo & Conditioner"],
    "shampooing": ["Shampoo & Conditioner"],
    "tandpasta": ["Toothpaste & Toothbrush"],
    "dentifrice": ["Toothpaste & Toothbrush"],
    "toothpaste": ["Toothpaste & Toothbrush"],
    "deodorant": ["Deodorant"],
    "déodorant": ["Deodorant"],
    "luier":     ["Baby Care"],
    "couche":    ["Baby Care"],
    "diaper":    ["Baby Care"],
    "wasmiddel": ["Laundry Care"],
    "lessive":   ["Laundry Care"],
    "detergent": ["Laundry Care"],
    "vaatwas":   ["Dishwashing"],
    "vaisselle": ["Dishwashing"],
    "schoonmaak": ["Surface Care"],
    "nettoyage":  ["Surface Care"],
    "wc":        ["Paper Products & Waste Bags"],
    "toilet":    ["Paper Products & Waste Bags"],
    # ── Pet Care ──
    "hond":   ["Dog Care"],
    "chien":  ["Dog Care"],
    "dog":    ["Dog Care"],
    "kat":    ["Cat Care"],
    "chat":   ["Cat Care"],
    "cat":    ["Cat Care"],
    # ── Other staples ──
    "pasta":  ["Staples Pasta Rice"],
    "rijst":  ["Staples Pasta Rice"],
    "riz":    ["Staples Pasta Rice"],
    "rice":   ["Staples Pasta Rice"],
    "olie":   ["Oils & Vinegars"],
    "huile":  ["Oils & Vinegars"],
    "oil":    ["Oils & Vinegars"],
    "azijn":  ["Oils & Vinegars"],
    "vinaigre": ["Oils & Vinegars"],
    "saus":   ["Condiments & Sauces"],
    "sauce":  ["Condiments & Sauces"],
    "soep":   ["Soups & Bouillons"],
    "soupe":  ["Soups & Bouillons"],
    "soup":   ["Soups & Bouillons"],
    "ontbijt": ["Breakfast & Cereals"],
    "petit-déjeuner": ["Breakfast & Cereals"],
    "petit déjeuner": ["Breakfast & Cereals"],
    "breakfast": ["Breakfast & Cereals"],
    "cereal":   ["Breakfast & Cereals"],
    "müsli":    ["Breakfast & Cereals"],
    "musli":    ["Breakfast & Cereals"],
    "muesli":   ["Breakfast & Cereals"],
    "honing":   ["Sweet Spreads & Honey"],
    "miel":     ["Sweet Spreads & Honey"],
    "honey":    ["Sweet Spreads & Honey"],
    "confiture": ["Sweet Spreads & Honey"],
    "jam":      ["Sweet Spreads & Honey"],
    "chips":    ["Salty Snacks & Nuts"],
    "snack":    ["Salty Snacks & Nuts"],
    "noten":    ["Salty Snacks & Nuts", "Dried Fruit & Nuts"],
    "noix":     ["Salty Snacks & Nuts", "Dried Fruit & Nuts"],
    "nuts":     ["Salty Snacks & Nuts", "Dried Fruit & Nuts"],
    "tabak":    ["Cigarettes & Rolling Tobacco", "Cigars & Cigarillos"],
    "tabac":    ["Cigarettes & Rolling Tobacco", "Cigars & Cigarillos"],
    "tobacco":  ["Cigarettes & Rolling Tobacco", "Cigars & Cigarillos"],
    "sigaret":  ["Cigarettes & Rolling Tobacco"],
    "cigarette": ["Cigarettes & Rolling Tobacco"],
}

_TERM_TO_GRANULARS: Dict[str, List[str]] = {}


def _unaccent(s: str) -> str:
    """Strip combining marks; preserves the rest of the string."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def _normalize_search_term(s: str) -> str:
    return _unaccent(s.strip().lower())


def _tokenize_display(s: str) -> List[str]:
    """Split a display string into searchable tokens (lowercased, unaccented).

    Keeps the full phrase too — so 'Personal Care' yields ['personal', 'care', 'personal care'].
    """
    norm = _normalize_search_term(s)
    # Replace separators with spaces, then split.
    cleaned = re.sub(r"[&/,()\-]+", " ", norm)
    words = [w for w in cleaned.split() if w and w not in _STOPWORDS]
    out = list(words)
    # Add the full multi-word phrase too if there are 2+ words.
    if len(words) >= 2:
        out.append(" ".join(words))
    return out


def _build_search_lookup() -> None:
    """Populate _TERM_TO_GRANULARS by walking _TREE + applying _SUB_CLUSTER_SYNONYMS."""

    def add_auto(term: str, granulars: List[str]) -> None:
        if not term or term in _STOPWORDS or term in _AUTODERIVE_BLOCKLIST:
            return
        bucket = _TERM_TO_GRANULARS.setdefault(term, [])
        for g in granulars:
            if g not in bucket:
                bucket.append(g)

    # 1. Auto-derive from group + parent display dicts.
    for group in _TREE:
        group_granulars: List[str] = []
        for cat in group["categories"]:
            if cat.get("excluded"):
                continue
            group_granulars.extend(cat.get("granular", []))

        for lang_text in group["group"].values():
            for token in _tokenize_display(lang_text):
                add_auto(token, group_granulars)

        for cat in group["categories"]:
            if cat.get("excluded"):
                continue
            cat_granulars = cat.get("granular", [])
            for display_dict_key in ("b2c_display", "b2b_display"):
                for lang_text in cat.get(display_dict_key, {}).values():
                    for token in _tokenize_display(lang_text):
                        add_auto(token, cat_granulars)

    # 2. Manually curated sub-cluster synonyms — authoritative, replace any
    #    auto-derived entry. The narrower curated list is exactly the point.
    for term, granulars in _SUB_CLUSTER_SYNONYMS.items():
        key = _normalize_search_term(term)
        if key:
            _TERM_TO_GRANULARS[key] = list(granulars)


_build_search_lookup()


def get_granulars_for_search_term(term: str) -> List[str]:
    """Map a user search term (en/nl/fr) to a list of granular_category names.

    Lookup is case- and accent-insensitive. Returns an empty list when no
    match is found — callers should still fall back to text similarity over
    display_name / brand / search_text.
    """
    if not term:
        return []
    key = _normalize_search_term(term)
    if not key:
        return []
    hit = _TERM_TO_GRANULARS.get(key)
    if hit is not None:
        return list(hit)
    # Multi-word query: try the longest matching prefix that resolves.
    # E.g. "bier blikjes" → "bier".
    parts = key.split()
    if len(parts) > 1:
        for n in range(len(parts), 0, -1):
            sub = " ".join(parts[:n])
            hit = _TERM_TO_GRANULARS.get(sub)
            if hit is not None:
                return list(hit)
    return []


def get_hierarchy(lang: str = "en", mode: str = "b2c") -> dict:
    """Get the full hierarchy as a dict for API responses."""
    groups = []
    for group in _TREE:
        group_name = group["group"].get(lang, group["group"]["en"])
        cat_list = []
        for cat in group["categories"]:

            # Select B2C or B2B display dict based on mode
            display_dict = cat.get(f"{mode}_display", cat.get("b2c_display"))
            display_name = display_dict.get(lang, display_dict.get("en", cat["name"]))

            cat_list.append({
                "name": cat["name"],
                "display_name": display_name,
                "sub_categories": cat.get("granular", []),
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

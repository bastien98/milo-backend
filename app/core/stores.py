"""
Supported store definitions — single source of truth for the entire app.

Defines which Belgian retailers are accepted for receipt processing.
All lookup dicts and constants are derived from _STORES at module load time.

Following the same pattern as app/core/categories.py.
"""

from typing import Dict, List, Optional


# ============================================================
# SINGLE SOURCE OF TRUTH
# ============================================================
#
# Each entry:
#   name         — Canonical DB name (lowercase, stored in receipts/transactions)
#   display_name — Clean display name for UI and LLM prompt
#   aliases      — Lowercase strings to match against LLM vendor_name output.
#                  Ordered longest-first within each store for correct prefix matching.
#
# Every sub-brand is a SEPARATE entry. The LLM is instructed to pick
# exactly one display_name from this list. Unknown stores → "Other".

_STORES = [
    # ── Colruyt Group ──
    {"name": "colruyt", "display_name": "Colruyt", "aliases": ["colruyt"], "has_promos": True},
    {"name": "okay", "display_name": "OKay", "aliases": ["okay", "o'kay"], "has_promos": True},
    {"name": "okay compact", "display_name": "OKay Compact", "aliases": ["okay compact"], "has_promos": False},
    {"name": "bio-planet", "display_name": "Bio-Planet", "aliases": ["bio-planet", "bio planet", "bioplanet"], "has_promos": False},
    {"name": "cru", "display_name": "Cru", "aliases": ["cru"], "has_promos": False},
    {"name": "spar", "display_name": "Spar", "aliases": ["spar"], "has_promos": True},
    {"name": "comarkt", "display_name": "Comarkt", "aliases": ["comarkt"], "has_promos": False},

    # ── Ahold Delhaize ──
    {"name": "delhaize", "display_name": "Delhaize", "aliases": ["ad delhaize", "delhaize"], "has_promos": True},
    {"name": "proxy delhaize", "display_name": "Proxy Delhaize", "aliases": ["proxy delhaize", "delhaize proxy"], "has_promos": False},
    {"name": "shop & go", "display_name": "Shop & Go", "aliases": ["shop & go", "shop&go", "delhaize shop & go"], "has_promos": False},

    # ── Carrefour ──
    {
        "name": "carrefour",
        "display_name": "Carrefour Hypermarket",
        "aliases": [
            "carrefour hypermarché",
            "carrefour hypermarkt",
            "carrefour hypermarket",
            "carrefour",
        ],
        "has_promos": True,
    },
    {"name": "carrefour market", "display_name": "Carrefour Market", "aliases": ["carrefour market"], "has_promos": True},
    {"name": "carrefour express", "display_name": "Carrefour Express", "aliases": ["carrefour express"], "has_promos": False},

    # ── Discounters ──
    {"name": "aldi", "display_name": "Aldi", "aliases": ["aldi"], "has_promos": True},
    {"name": "lidl", "display_name": "Lidl", "aliases": ["lidl"], "has_promos": True},

    # ── Albert Heijn ──
    {"name": "albert heijn", "display_name": "Albert Heijn", "aliases": ["albert heijn", "ah"], "has_promos": True},
    {"name": "ah to go", "display_name": "AH To Go", "aliases": ["ah to go", "albert heijn to go"], "has_promos": False},

    # ── Other Belgian retailers ──
    {"name": "intermarche", "display_name": "Intermarché", "aliases": ["intermarché", "intermarche"], "has_promos": True},
    {"name": "match", "display_name": "Match", "aliases": ["match"], "has_promos": False},
    {"name": "makro", "display_name": "Makro", "aliases": ["makro"], "has_promos": False},
    {"name": "jumbo", "display_name": "Jumbo", "aliases": ["jumbo"], "has_promos": True},

    # ── Fallback ──
    {"name": "other", "display_name": "Other", "aliases": ["other"], "has_promos": False},
]


# ============================================================
# DERIVED LOOKUPS (built once at module load time)
# ============================================================

# (alias, canonical_name) pairs sorted by alias length descending,
# so "carrefour market" is tried before "carrefour".
ALLOWED_STORE_ALIASES: List[tuple] = []

# canonical name → display name
STORE_DISPLAY_NAMES: Dict[str, str] = {}

# canonical name → whether the store has promo recommendations
STORE_HAS_PROMOS: Dict[str, bool] = {}

# All canonical store names
ALL_STORE_NAMES: List[str] = []

# Stores that support promo recommendations
PROMO_STORE_NAMES: List[str] = []


def _build_lookups() -> None:
    """Build all lookup tables from _STORES at module load time."""
    alias_pairs = []

    for store in _STORES:
        name = store["name"]
        ALL_STORE_NAMES.append(name)
        STORE_DISPLAY_NAMES[name] = store["display_name"]
        STORE_HAS_PROMOS[name] = store.get("has_promos", False)
        if store.get("has_promos", False):
            PROMO_STORE_NAMES.append(name)

        for alias in store["aliases"]:
            alias_pairs.append((alias, name))

    # Sort by alias length descending so longest prefixes match first
    alias_pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
    ALLOWED_STORE_ALIASES.extend(alias_pairs)


_build_lookups()


# ============================================================
# PROMPT HELPERS
# ============================================================

# Comma-separated display names for injection into LLM prompts
STORES_PROMPT_LIST: str = ", ".join(
    store["display_name"] for store in _STORES
)


# ============================================================
# PUBLIC API
# ============================================================

def resolve_store_name(vendor_name: str) -> Optional[str]:
    """Resolve a vendor name from LLM output to a canonical store name.

    Uses longest-prefix matching so "carrefour market etterbeek"
    matches "carrefour market" → "carrefour market" (not just "carrefour").

    Returns the canonical lowercase store name (e.g. "colruyt", "carrefour"),
    or None if the store is not in the supported list.
    """
    if not vendor_name:
        return None

    normalized = vendor_name.lower().strip()

    for alias, canonical in ALLOWED_STORE_ALIASES:
        if normalized == alias or normalized.startswith(alias + " "):
            return canonical

    return None


def get_store_display_name(canonical_name: str) -> str:
    """Get the display name for a canonical store name."""
    return STORE_DISPLAY_NAMES.get(canonical_name, canonical_name)


def get_all_store_names() -> List[str]:
    """Get all canonical store names."""
    return ALL_STORE_NAMES.copy()


def has_promos(store_name: str) -> bool:
    """Check if a store supports promo recommendations."""
    return STORE_HAS_PROMOS.get(store_name, False)


def get_promo_store_names() -> List[str]:
    """Get canonical names of stores that support promo recommendations."""
    return PROMO_STORE_NAMES.copy()


def is_supported_store(vendor_name: str) -> bool:
    """Check if a vendor name maps to a supported store."""
    return resolve_store_name(vendor_name) is not None

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
#   display_name — Clean display name for UI
#   aliases      — Lowercase prefixes to match against LLM vendor_name output.
#                  Ordered longest-first within each store for correct prefix matching.

_STORES = [
    {
        "name": "colruyt",
        "display_name": "Colruyt",
        "aliases": ["colruyt"],
    },
    {
        "name": "delhaize",
        "display_name": "Delhaize",
        "aliases": ["delhaize"],
    },
    {
        "name": "carrefour",
        "display_name": "Carrefour",
        "aliases": [
            "carrefour hypermarché",
            "carrefour hypermarkt",
            "carrefour market",
            "carrefour express",
            "carrefour",
        ],
    },
    {
        "name": "aldi",
        "display_name": "Aldi",
        "aliases": ["aldi"],
    },
    {
        "name": "lidl",
        "display_name": "Lidl",
        "aliases": ["lidl"],
    },
    {
        "name": "albert heijn",
        "display_name": "Albert Heijn",
        "aliases": ["albert heijn", "ah"],
    },
]


# ============================================================
# DERIVED LOOKUPS (built once at module load time)
# ============================================================

# (alias, canonical_name) pairs sorted by alias length descending,
# so "carrefour market" is tried before "carrefour".
ALLOWED_STORE_ALIASES: List[tuple] = []

# canonical name → display name
STORE_DISPLAY_NAMES: Dict[str, str] = {}

# All canonical store names
ALL_STORE_NAMES: List[str] = []


def _build_lookups() -> None:
    """Build all lookup tables from _STORES at module load time."""
    alias_pairs = []

    for store in _STORES:
        name = store["name"]
        ALL_STORE_NAMES.append(name)
        STORE_DISPLAY_NAMES[name] = store["display_name"]

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
    matches "carrefour market" → "carrefour" (not just "carrefour").

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


def is_supported_store(vendor_name: str) -> bool:
    """Check if a vendor name maps to a supported store."""
    return resolve_store_name(vendor_name) is not None

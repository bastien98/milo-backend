"""Retailer configuration for promopromo.be scraping.

Maps internal store keys to promopromo.be shop slugs, UUIDs, and ingestion limits.
Shop UUIDs are stable identifiers — folder UUIDs change weekly.
"""

RETAILERS = {
    "albert_heijn": {
        "shop_slug": "albert-heijn",
        "shop_uuid": "80726055-be83-426a-8279-37117a18fd21",
        "store_id": "albert heijn",
        "max_folders": 1,
    },
    "colruyt": {
        "shop_slug": "colruyt",
        "shop_uuid": "86bddb08-7894-4325-bfa8-71ee23c0f26d",
        "store_id": "colruyt",
        "max_folders": 1,
    },
    "carrefour_hyper": {
        "shop_slug": "carrefour",
        "shop_uuid": "8d539087-ab3c-445c-9748-ac98cbab3ee7",
        "store_id": "carrefour",
        "max_folders": 6,
    },
    "carrefour_market": {
        "shop_slug": "carrefour-market",
        "shop_uuid": "f5d88345-9658-47c2-9406-a57bfc17c6c8",
        "store_id": "carrefour market",
        "max_folders": 2,
    },
    "delhaize": {
        "shop_slug": "delhaize",
        "shop_uuid": "d7dbd268-36d1-4230-a633-c1dcb3ad3400",
        "store_id": "delhaize",
        "max_folders": 6,
    },
    "jumbo": {
        "shop_slug": "jumbo",
        "shop_uuid": "22c47cef-8cc8-42c4-ae18-ef8bf413f3da",
        "store_id": "jumbo",
        "max_folders": 2,
    },
    "okay": {
        "shop_slug": "okay",
        "shop_uuid": "945c0671-df9e-4fe7-b4e6-5a99225b35e6",
        "store_id": "okay",
        "max_folders": 1,
    },
    "spar": {
        "shop_slug": "spar",
        "shop_uuid": "0ae0bee8-dc4e-45b1-92aa-1810ea085353",
        "store_id": "spar",
        "max_folders": 1,
    },
}

PROMOPROMO_BASE = "https://www.promopromo.be"
PROMOPROMO_CDN = "https://cdn.jafolders.com"


def get_retailer(key: str) -> dict:
    """Get retailer config by key. Raises KeyError if not found."""
    if key not in RETAILERS:
        raise KeyError(
            f"Unknown retailer '{key}'. Available: {', '.join(sorted(RETAILERS))}"
        )
    return RETAILERS[key]


def list_retailers() -> list[str]:
    """Return all available retailer keys."""
    return sorted(RETAILERS.keys())

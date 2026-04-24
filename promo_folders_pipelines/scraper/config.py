"""Retailer configuration for promopromo.be scraping.

Maps internal store keys to promopromo.be shop slugs and UUIDs.
Shop UUIDs are stable identifiers — folder UUIDs change weekly.
"""

RETAILERS = {
    "albert_heijn": {
        "shop_slug": "albert-heijn",
        "shop_uuid": "80726055-be83-426a-8279-37117a18fd21",
        "store_id": "albert heijn",
    },
    "colruyt": {
        "shop_slug": "colruyt",
        "shop_uuid": "86bddb08-7894-4325-bfa8-71ee23c0f26d",
        "store_id": "colruyt",
    },
    "carrefour_hyper": {
        "shop_slug": "carrefour",
        "shop_uuid": "8d539087-ab3c-445c-9748-ac98cbab3ee7",
        "store_id": "carrefour",
    },
    "carrefour_market": {
        "shop_slug": "carrefour-market",
        "shop_uuid": "f5d88345-9658-47c2-9406-a57bfc17c6c8",
        "store_id": "carrefour market",
    },
    "delhaize": {
        "shop_slug": "delhaize",
        "shop_uuid": "d7dbd268-36d1-4230-a633-c1dcb3ad3400",
        "store_id": "delhaize",
    },
    "intermarche": {
        "shop_slug": "intermarche",
        "shop_uuid": "f43e6d61-38d3-4211-b093-7b9b79f8e4e5",
        "store_id": "intermarche",
    },
    "jumbo": {
        "shop_slug": "jumbo",
        "shop_uuid": "22c47cef-8cc8-42c4-ae18-ef8bf413f3da",
        "store_id": "jumbo",
    },
    "lidl": {
        "shop_slug": "lidl",
        "shop_uuid": "219b66e2-2bb2-4df9-9f98-cc66b7159eef",
        "store_id": "lidl",
    },
    "aldi": {
        "shop_slug": "aldi",
        "shop_uuid": "d5abeff7-16e7-4e0a-98dc-1c8105ee1d15",
        "store_id": "aldi",
    },
    "okay": {
        "shop_slug": "okay",
        "shop_uuid": "945c0671-df9e-4fe7-b4e6-5a99225b35e6",
        "store_id": "okay",
    },
    "spar": {
        "shop_slug": "spar",
        "shop_uuid": "0ae0bee8-dc4e-45b1-92aa-1810ea085353",
        "store_id": "spar",
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

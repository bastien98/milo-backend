"""
Store config loader — reads YAML configs from promo_folders_pipelines/stores/.

Each YAML file defines one store's promo extraction configuration.
Validates that each YAML's store_id matches the canonical names in app/core/stores.py.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.core.stores import ALL_STORE_NAMES


_STORES_DIR = Path(__file__).resolve().parent


def load_store_config(store_id: str) -> Dict[str, Any]:
    """Load a store's YAML configuration by store_id.

    Raises FileNotFoundError if the config does not exist.
    Raises ValueError if the YAML's store_id is not a canonical name in app/core/stores.py.
    """
    config_path = _STORES_DIR / f"{store_id}.yaml"
    if not config_path.exists():
        raise FileNotFoundError(
            f"No config found for store '{store_id}' at {config_path}. "
            f"Available stores: {', '.join(list_stores())}"
        )
    with open(config_path) as f:
        config = yaml.safe_load(f)

    canonical = config.get("store_id")
    if canonical not in ALL_STORE_NAMES:
        raise ValueError(
            f"YAML store_id '{canonical}' (from {config_path.name}) "
            f"is not a canonical store name in app/core/stores.py. "
            f"Valid names: {', '.join(ALL_STORE_NAMES)}"
        )

    return config


def list_stores() -> List[str]:
    """Return all available store IDs (YAML filenames without extension)."""
    return sorted(
        p.stem for p in _STORES_DIR.glob("*.yaml")
    )

"""
Store config loader — reads YAML configs from ai/promo_pipelines/stores/.

Each YAML file defines one store's promo extraction configuration.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


_STORES_DIR = Path(__file__).resolve().parent


def load_store_config(store_id: str) -> Dict[str, Any]:
    """Load a store's YAML configuration by store_id.

    Raises FileNotFoundError if the config does not exist.
    """
    config_path = _STORES_DIR / f"{store_id}.yaml"
    if not config_path.exists():
        raise FileNotFoundError(
            f"No config found for store '{store_id}' at {config_path}. "
            f"Available stores: {', '.join(list_stores())}"
        )
    with open(config_path) as f:
        return yaml.safe_load(f)


def list_stores() -> List[str]:
    """Return all available store IDs (YAML filenames without extension)."""
    return sorted(
        p.stem for p in _STORES_DIR.glob("*.yaml")
    )

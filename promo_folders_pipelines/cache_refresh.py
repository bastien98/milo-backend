"""POST to /promos/folders/refresh so the API drops its in-memory cache.

Shared by both ingest entry points (`ingest.py` and `scraper/daily_pipeline.py`)
so each invalidation path behaves identically.
"""

import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


def notify_folders_cache_refresh(env: str) -> None:
    """POST to /promos/folders/refresh so the API drops its in-memory cache.

    Best-effort — any failure is logged but does not fail the ingestion run.
    Requires `PROMO_FOLDERS_REFRESH_TOKEN` in the environment; the same token
    must be set on the target Railway service.
    """
    if env == "prod":
        base = "https://scandalicious-api-production.up.railway.app"
    else:
        base = "https://scandalicious-api-non-prod.up.railway.app"
    url = f"{base}/api/v2/promos/folders/refresh"

    token = os.environ.get("PROMO_FOLDERS_REFRESH_TOKEN", "")
    if not token:
        logger.warning(
            "PROMO_FOLDERS_REFRESH_TOKEN not set — skipping folders cache refresh. "
            "New hotspots may take up to 1 hour to surface in /promos/folders."
        )
        return

    req = urllib.request.Request(
        url,
        method="POST",
        headers={"X-Refresh-Token": token},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 204:
                logger.info(f"Folders cache refresh requested ({env})")
            else:
                logger.warning(f"Folders cache refresh returned HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        logger.warning(f"Folders cache refresh rejected: HTTP {e.code} — {e.reason}")
    except Exception as e:
        logger.warning(f"Folders cache refresh failed: {e}")

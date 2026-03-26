"""
Promo Search Service

Stub — search is temporarily disabled while migrating from Pinecone to PostgreSQL.
Will be re-implemented with pg_trgm-based search.
"""

import logging
from typing import Optional

from app.schemas.promo import PromoSearchResult

logger = logging.getLogger(__name__)


class PromoSearchService:
    """Promo search service (currently stubbed — returns empty results)."""

    def __init__(self):
        pass

    async def search(
        self,
        query: str,
        stores: list[str],
    ) -> list[PromoSearchResult]:
        """Search for promos matching a query. Currently returns empty results."""
        logger.info(f"[promo_search] Search disabled (query='{query}', stores={stores})")
        return []

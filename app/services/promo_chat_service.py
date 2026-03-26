"""
Promo Chat Service

Stub — promo chat search is temporarily disabled while migrating from Pinecone to PostgreSQL.
Will be re-implemented with pg_trgm-based search.
"""

import logging
from typing import Optional

from app.models.enums import Language
from app.schemas.promo_chat import (
    PromoChatMessage,
    PromoChatResponse,
)

logger = logging.getLogger(__name__)


class PromoChatService:
    """Promo chat service (currently stubbed — returns empty results)."""

    def __init__(self):
        pass

    async def chat(
        self,
        message: str,
        conversation_history: Optional[list[PromoChatMessage]] = None,
        language: Optional[Language] = None,
    ) -> PromoChatResponse:
        """Process a promo chat message. Currently returns a disabled message."""
        logger.info(f"[promo_chat] Chat search disabled (message='{message[:50]}')")

        msg = "Promo search is temporarily unavailable. Check back soon!"
        if language and language.value == "nl":
            msg = "Promo zoeken is tijdelijk niet beschikbaar. Probeer later opnieuw!"
        elif language and language.value == "fr":
            msg = "La recherche de promos est temporairement indisponible. Réessayez bientôt !"

        return PromoChatResponse(
            message=msg,
            promos=[],
            search_query=None,
            needs_clarification=False,
        )

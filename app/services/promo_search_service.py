"""
Promo Search Service

Handles structured promo search:
1. Optimises the user query via Gemini 3.1 Flash-Lite (structured output)
2. Searches Pinecone promos index with store + expiry filters
3. Returns ranked promo results
"""

import logging
import os
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel as PydanticBaseModel, Field
from pinecone import Pinecone

from app.core.categories import CATEGORIES_PROMPT_LIST
from app.schemas.promo import PromoSearchResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pinecone configuration (shared with promo_chat_service)
# ---------------------------------------------------------------------------
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY", "")
PINECONE_INDEX_HOST = "promos-k16b2f4.svc.aped-4627-b74a.pinecone.io"

# Search tuning
SEARCH_TOP_K = 30
RERANK_TOP_N = 15
RERANK_SCORE_THRESHOLD = 0.40

# ---------------------------------------------------------------------------
# LLM structured output schema
# ---------------------------------------------------------------------------

class _PromoSearchIntent(PydanticBaseModel):
    """Structured output from Gemini — single search_text field."""
    search_text: str = Field(
        description="'brand product [category]' — lowercase, no quantities/packaging",
    )


# ---------------------------------------------------------------------------
# LLM system prompt
# ---------------------------------------------------------------------------

SEARCH_INTENT_PROMPT = f"""<role>
You are a search query optimizer for a Belgian supermarket promo index.
Your job is to transform user search queries into optimized search parameters
that maximize recall against a vector database of grocery promotions.
</role>

<context>
The promo index stores items with a text field in this format:
  display_name (lowercased) [granular_category]
Examples of real indexed text:
  "côte d'or chocolade tabletten 200 g [Chocolate Bars]"
  "pampers luiers premium protection maat 4 [Diapers]"
  "coca-cola zero 1,5 l [Cola]"
  "danone activia vanille 4 x 125 g [Yoghurt Natural]"
  "jupiler pils 24 x 25 cl [Beer Pils]"
</context>

<task>
Given a user's search query, produce:
1. search_text — matching the index format above. ALL LOWERCASE.
   - Include brand and product name
   - Translate to Dutch if user writes in English/French (the index is primarily Dutch)
   - Append your FIRST granular_category guess in [square brackets]
     IMPORTANT: the category in brackets MUST be one of the EXACT names from the <categories> list below. Do NOT invent category names.
(search_text is the only output — it goes directly to Pinecone as the search query)
</task>

<categories>
{CATEGORIES_PROMPT_LIST}
</categories>

<examples>
User: "Pampers diapers" → search_text: "pampers luiers [Diapers]"
User: "Coca-Cola" → search_text: "coca-cola [Cola]"
User: "something sweet for breakfast" → search_text: "confituur [Spreads Jam]"
User: "bière" → search_text: "bier [Beer Pils]"
User: "Côte d'Or chocolat" → search_text: "côte d'or chocolade [Chocolate Bars]"
User: "chips" → search_text: "chips [Chips]"
User: "yoghurt" → search_text: "yoghurt [Yoghurt Natural]"
</examples>"""


class PromoSearchService:
    """Structured promo search: LLM query optimisation → Pinecone search."""

    def __init__(self):
        self.pc = None
        self.index = None
        if PINECONE_API_KEY:
            self.pc = Pinecone(api_key=PINECONE_API_KEY)
            self.index = self.pc.Index(host=PINECONE_INDEX_HOST)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        stores: list[str],
    ) -> list[PromoSearchResult]:
        """Search promos by LLM-optimised query text + store filters."""
        if not self.index:
            logger.error("Pinecone index not initialised")
            return []

        # 1. LLM query optimisation
        intent = await self._optimize_query(query)
        search_text = intent.search_text if intent else query
        logger.info(f"[promo_search] query='{query}' → search_text='{search_text}'")

        # 2. Build filter: stores + expiry
        today_epoch = int(date.today().strftime("%Y%m%d"))
        store_filter = (
            {"source_retailer": {"$eq": stores[0]}}
            if len(stores) == 1
            else {"source_retailer": {"$in": stores}}
        )
        search_filter = {
            "$and": [store_filter, {"validity_end_epoch": {"$gte": today_epoch}}]
        }

        # 3. Single Pinecone search + rerank
        hits = self._pinecone_search_and_rerank(search_text, search_filter)

        # 4. Build results
        results: list[PromoSearchResult] = []
        for hit in hits:
            score = hit.get("_score", 0)
            if score < RERANK_SCORE_THRESHOLD:
                continue
            result = self._build_result(hit.get("fields", {}), score)
            if result and self._is_valid(result) and not self._is_expired(result):
                results.append(result)

        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:RERANK_TOP_N]

    # ------------------------------------------------------------------
    # LLM query optimisation
    # ------------------------------------------------------------------

    async def _optimize_query(self, query: str) -> Optional[_PromoSearchIntent]:
        """Use Gemini 3.1 Flash-Lite to optimise the search query."""
        gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
        if not gemini_api_key:
            logger.warning("No GEMINI_API_KEY — skipping query optimisation")
            return None

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=gemini_api_key)
            response = client.models.generate_content(
                model="gemini-3.1-flash-lite-preview",
                contents=[query],
                config=types.GenerateContentConfig(
                    system_instruction=SEARCH_INTENT_PROMPT,
                    max_output_tokens=300,
                    temperature=1.0,
                    response_mime_type="application/json",
                    response_schema=_PromoSearchIntent,
                ),
            )
            intent = _PromoSearchIntent.model_validate_json(response.text)
            logger.info(f"[promo_search] LLM optimised: '{query}' → '{intent.search_text}'")
            return intent

        except Exception as e:
            logger.warning(f"[promo_search] LLM optimisation failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Pinecone search (adapted from promo_chat_service)
    # ------------------------------------------------------------------

    def _pinecone_search_and_rerank(
        self, query_text: str, filter_dict: Optional[dict]
    ) -> list[dict]:
        """Execute integrated search + rerank in a single Pinecone API call."""
        logger.info(f"[promo_search] pinecone query='{query_text}' filter={filter_dict}")

        query = {"inputs": {"text": query_text}, "top_k": SEARCH_TOP_K}
        if filter_dict:
            query["filter"] = filter_dict

        rerank = {
            "model": "bge-reranker-v2-m3",
            "rank_fields": ["text"],
            "top_n": RERANK_TOP_N,
        }

        try:
            results = self.index.search_records(
                namespace="__default__", query=query, rerank=rerank
            )
            return self._extract_hits(results)
        except (AttributeError, TypeError):
            try:
                results = self.index.search(
                    namespace="__default__", query=query, rerank=rerank
                )
                return self._extract_hits(results)
            except Exception as e:
                logger.warning(f"[promo_search] Pinecone search failed: {e}")
                return []

    def _extract_hits(self, results) -> list[dict]:
        """Extract hits from Pinecone search response."""
        if hasattr(results, "result"):
            result = results.result
            if hasattr(result, "hits"):
                return [self._normalize_hit(h) for h in result.hits]

        if isinstance(results, dict):
            if "result" in results:
                return [
                    self._normalize_hit(h)
                    for h in results["result"].get("hits", [])
                ]
            if "matches" in results:
                return [self._normalize_hit(m) for m in results["matches"]]

        if hasattr(results, "matches"):
            return [self._normalize_hit(m) for m in results.matches]

        return []

    @staticmethod
    def _normalize_hit(hit) -> dict:
        """Normalize a Pinecone hit into a consistent dict format."""
        if isinstance(hit, dict):
            if "fields" not in hit and "metadata" in hit:
                hit["fields"] = hit["metadata"]
            return hit

        d = {
            "_id": getattr(hit, "_id", getattr(hit, "id", "")),
            "_score": getattr(hit, "_score", getattr(hit, "score", 0)),
        }
        if hasattr(hit, "fields"):
            d["fields"] = (
                dict(hit.fields) if not isinstance(hit.fields, dict) else hit.fields
            )
        elif hasattr(hit, "metadata"):
            d["fields"] = (
                dict(hit.metadata)
                if not isinstance(hit.metadata, dict)
                else hit.metadata
            )
        else:
            d["fields"] = {}
        return d

    # ------------------------------------------------------------------
    # Result building (adapted from promo_chat_service)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_result(
        fields: dict, score: float
    ) -> Optional[PromoSearchResult]:
        """Build a PromoSearchResult from Pinecone fields."""
        try:
            original_price = None
            promo_price = None
            savings_amount = None
            discount_percent = None

            if fields.get("original_price"):
                try:
                    original_price = float(fields["original_price"])
                except (ValueError, TypeError):
                    pass

            if fields.get("promo_price"):
                try:
                    promo_price = float(fields["promo_price"])
                except (ValueError, TypeError):
                    pass

            if fields.get("savings_amount"):
                try:
                    savings_amount = float(fields["savings_amount"])
                except (ValueError, TypeError):
                    pass

            if savings_amount and original_price and original_price > 0:
                discount_percent = round((savings_amount / original_price) * 100, 1)

            return PromoSearchResult(
                product_name=fields.get("display_name", "Unknown"),
                brand=None,
                category=fields.get(
                    "granular_category", fields.get("parent_category", "Other")
                ),
                store=fields.get("source_retailer", "Unknown"),
                original_price=original_price,
                promo_price=promo_price,
                savings=savings_amount,
                discount_percent=discount_percent,
                mechanism=fields.get("display_mechanism"),
                validity_start=fields.get("validity_start"),
                validity_end=fields.get("validity_end"),
                display_name=fields.get("display_name"),
                display_mechanism=fields.get("display_mechanism"),
                display_description=fields.get("display_description"),
                display_unit_price=fields.get("display_unit_price"),
                relevance_score=round(score, 3),
                page_number=None,
                promo_folder_url=fields.get("promo_folder_url"),
            )
        except Exception as e:
            logger.warning(f"[promo_search] Failed to build result: {e}")
            return None

    @staticmethod
    def _is_valid(result: PromoSearchResult) -> bool:
        """Check if a promo has valid pricing data."""
        if result.original_price is not None and result.promo_price is not None:
            if result.original_price <= 0:
                return False
            if result.promo_price > result.original_price:
                return False
        return True

    @staticmethod
    def _is_expired(result: PromoSearchResult) -> bool:
        """Safety net: check if promo is expired based on validity_end string."""
        if not result.validity_end:
            return False
        try:
            end_date = datetime.strptime(result.validity_end, "%Y-%m-%d").date()
            return end_date < date.today()
        except (ValueError, TypeError):
            return False

"""
Promo Chat Service

Handles promo search chat interactions:
1. Uses LLM to extract structured search parameters from natural language
2. Searches Pinecone promos index with optimized queries
3. Returns structured promo results with a friendly response
"""

import json
import logging
import os
from datetime import date, datetime
from typing import Optional

from pinecone import Pinecone

from app.config import get_settings
from app.schemas.promo_chat import (
    PromoChatMessage,
    PromoChatResponse,
    PromoResult,
    SearchQuery,
)
from app.services.categories import CATEGORIES_PROMPT_LIST

logger = logging.getLogger(__name__)
settings = get_settings()

# Pinecone configuration
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY", "")
PINECONE_INDEX_HOST = "promos-k16b2f4.svc.aped-4627-b74a.pinecone.io"

# Search tuning
SEARCH_TOP_K = 30
RERANK_TOP_N = 10
RERANK_SCORE_THRESHOLD = 0.40  # Threshold for non-filtered searches

# Belgian supermarket chains for retailer matching
BELGIAN_RETAILERS = [
    "colruyt", "delhaize", "carrefour", "aldi", "lidl", "spar",
    "albert heijn", "bio-planet", "okay", "jumbo", "intermarché",
    "cora", "match", "louis delhaize", "proxy delhaize"
]

# LLM prompt for intent extraction - uses CATEGORIES_PROMPT_LIST dynamically
INTENT_EXTRACTION_PROMPT = f"""You are a promo search assistant for Belgian supermarkets. Your job is to extract structured search parameters from user queries about grocery promotions.

BELGIAN RETAILERS: Colruyt, Delhaize, Carrefour, Aldi, Lidl, Spar, Albert Heijn, Bio-Planet, Okay, Jumbo, Intermarché, Cora, Match, Louis Delhaize, Proxy Delhaize

GRANULAR CATEGORIES (use these EXACT names for granular_categories):
{CATEGORIES_PROMPT_LIST}

Extract the following from the user's message:

1. search_text: Format as "BRAND NORMALIZED_NAME (GRANULAR_CATEGORY)" - ALL LOWERCASE

   NORMALIZATION RULES (aligned with receipt/promo indexing):
   - Everything LOWERCASE
   - Remove quantities (500g, 1L, 6x33cl) and packaging (PET, blik, fles)
   - For normalized_name, remove manufacturer brands UNLESS brand IS the product identity:

     REMOVE brand from normalized_name (brand + generic product):
     - "Vandemoortele vinaigrette" → brand="vandemoortele", normalized_name="vinaigrette"
     - "Philadelphia cheese" → brand="philadelphia", normalized_name="kaas"
     - "Pampers diapers" → brand="pampers", normalized_name="luiers"
     - "Devos Lemmens mayo" → brand="devos lemmens", normalized_name="mayonaise"
     - "Lay's chips" → brand="lay's", normalized_name="chips paprika" (or just "chips")

     KEEP brand IN normalized_name (brand IS the product, removing leaves too generic name):
     - "Jupiler" → brand="jupiler", normalized_name="jupiler" (without = "bier pils", too generic)
     - "Coca-Cola Zero" → brand="coca-cola", normalized_name="coca-cola zero"
     - "Leffe Bruin" → brand="leffe", normalized_name="leffe bruin"
     - "Nutella" → brand="nutella", normalized_name="nutella"

   - Maintain original language (Dutch: kaas, bier, luiers / French: fromage, bière)

2. product_keywords: Normalized product names in Dutch (lowercase): ["kaas", "bier", "luiers"]

3. brands: Brand names (lowercase): ["philadelphia", "jupiler", "pampers"]

4. categories: Broad categories: ["Dairy", "Beverages", "Baby"]

5. granular_categories: EXACTLY 3 guesses using EXACT names from the category list above

6. retailers: Normalized retailer names if mentioned

7. is_vague: true for "any deals?", "what's cheap?" with no product info

8. clarification_needed: Question to ask if is_vague=true

EXAMPLES:
- "Philadelphia" → search_text: "philadelphia kaas (Cheese Spread)", granular_categories: ["Cheese Spread", "Cheese Fresh", "Cheese Soft"]
- "Jupiler" → search_text: "jupiler (Beer Pils)", granular_categories: ["Beer Pils", "Beer Special", "Beer Abbey Trappist"]
- "Pampers" → search_text: "pampers luiers (Diapers)", granular_categories: ["Diapers", "Baby Care", "Baby Food"]
- "coffee" → search_text: "koffie (Coffee Beans Ground)", granular_categories: ["Coffee Beans Ground", "Coffee Capsules", "Coffee Instant"]
- "Côte d'Or" → search_text: "côte d'or chocolade (Chocolate Bars)", granular_categories: ["Chocolate Bars", "Chocolate Pralines", "Candy"]
- "Coca-Cola" → search_text: "coca-cola (Cola)", granular_categories: ["Cola", "Lemonade & Soda", "Energy Drinks"]

RULES:
- search_text MUST be ALL LOWERCASE
- Format: "brand normalized_name (granular_category)" or "brand (granular_category)" if brand IS product
- ALWAYS provide exactly 3 granular_categories using EXACT names from the list
- Return ONLY valid JSON

Respond with ONLY a JSON object in this exact format:
{{
  "search_text": "string",
  "product_keywords": ["string"],
  "brands": ["string"],
  "categories": ["string"],
  "granular_categories": ["string", "string", "string"],
  "retailers": ["string"],
  "is_vague": boolean,
  "clarification_needed": "string or null"
}}"""


class PromoChatService:
    """Service for handling promo search chat interactions."""

    def __init__(self):
        self.pc = None
        self.index = None
        if PINECONE_API_KEY:
            self.pc = Pinecone(api_key=PINECONE_API_KEY)
            self.index = self.pc.Index(host=PINECONE_INDEX_HOST)

    async def chat(
        self,
        message: str,
        conversation_history: Optional[list[PromoChatMessage]] = None,
    ) -> PromoChatResponse:
        """
        Process a promo search chat message.

        1. Extract structured search parameters using LLM
        2. If query is vague, ask for clarification
        3. Search Pinecone for matching promos
        4. Return structured response with promos
        """
        # Step 1: Extract search parameters
        search_query = await self._extract_search_intent(message, conversation_history)

        # Step 2: Check if clarification needed
        if search_query.is_vague:
            return PromoChatResponse(
                message=search_query.clarification_needed or "Could you be more specific about what products or promotions you're looking for?",
                promos=[],
                search_query=search_query,
                needs_clarification=True,
            )

        # Step 3: Search Pinecone
        promos = await self._search_promos(search_query)

        # Step 4: Build response
        if promos:
            response_message = self._build_success_response(search_query, promos)
        else:
            response_message = self._build_no_results_response(search_query)

        return PromoChatResponse(
            message=response_message,
            promos=promos,
            search_query=search_query,
            needs_clarification=False,
        )

    async def _extract_search_intent(
        self,
        message: str,
        conversation_history: Optional[list[PromoChatMessage]] = None,
    ) -> SearchQuery:
        """Use LLM to extract structured search parameters from the user message."""
        # Build context from conversation history
        context = ""
        if conversation_history:
            context = "Previous conversation:\n"
            for msg in conversation_history[-4:]:  # Last 4 messages for context
                context += f"{msg.role}: {msg.content}\n"
            context += "\n"

        user_prompt = f"{context}User message: {message}\n\nExtract search parameters:"

        try:
            response_text = await self._call_llm(
                system_prompt=INTENT_EXTRACTION_PROMPT,
                user_message=user_prompt,
            )

            # Parse JSON response
            # Clean up response in case LLM adds markdown code blocks
            clean_response = response_text.strip()
            if clean_response.startswith("```"):
                clean_response = clean_response.split("```")[1]
                if clean_response.startswith("json"):
                    clean_response = clean_response[4:]
            clean_response = clean_response.strip()

            parsed = json.loads(clean_response)
            return SearchQuery(**parsed)

        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Failed to parse LLM intent response: {e}")
            # Fallback: use the message directly as search text
            return SearchQuery(
                search_text=message,
                product_keywords=[message],
                brands=[],
                categories=[],
                retailers=[],
                is_vague=len(message.split()) < 2,
                clarification_needed="What specific product or category are you looking for?" if len(message.split()) < 2 else None,
            )

    async def _call_llm(self, system_prompt: str, user_message: str) -> str:
        """Call the LLM for intent extraction."""
        gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
        anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        if gemini_api_key:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=gemini_api_key)
            response = client.models.generate_content(
                model="gemini-2.0-flash",  # Fast model for intent extraction
                contents=[user_message],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=500,
                    temperature=0.1,  # Low temperature for consistent structured output
                ),
            )
            return response.text

        elif anthropic_api_key:
            import anthropic

            client = anthropic.Anthropic(api_key=anthropic_api_key)
            response = client.messages.create(
                model="claude-3-5-haiku-20241022",  # Fast model for intent extraction
                max_tokens=500,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            return response.content[0].text

        else:
            # Fallback: simple keyword extraction without LLM
            logger.warning("No LLM API key available, using fallback extraction")
            return json.dumps({
                "search_text": user_message,
                "product_keywords": user_message.split(),
                "brands": [],
                "categories": [],
                "retailers": [r for r in BELGIAN_RETAILERS if r in user_message.lower()],
                "is_vague": len(user_message.split()) < 2,
                "clarification_needed": None,
            })

    async def _search_promos(self, search_query: SearchQuery) -> list[PromoResult]:
        """Search Pinecone for matching promotions using 3 category-filtered searches."""
        if not self.index:
            logger.error("Pinecone index not initialized")
            return []

        # Build base filter for retailers
        base_filter = None
        if search_query.retailers:
            normalized_retailers = []
            for r in search_query.retailers:
                r_lower = r.lower()
                for belgian_r in BELGIAN_RETAILERS:
                    if r_lower in belgian_r or belgian_r in r_lower:
                        normalized_retailers.append(belgian_r)
                        break
            if normalized_retailers:
                if len(normalized_retailers) == 1:
                    base_filter = {"source_retailer": {"$eq": normalized_retailers[0]}}
                else:
                    base_filter = {"source_retailer": {"$in": normalized_retailers}}

        all_promos = []
        seen_ids = set()

        # Expiration filter: only return promos that haven't expired yet
        today_epoch = int(date.today().strftime("%Y%m%d"))
        expiry_filter = {"validity_end_epoch": {"$gte": today_epoch}}

        # Inject expiry into base_filter
        if base_filter:
            base_filter = {"$and": [base_filter, expiry_filter]}
        else:
            base_filter = expiry_filter

        # Run 3 searches with granular_category filters (if available)
        granular_categories = search_query.granular_categories[:3] if search_query.granular_categories else []

        if granular_categories:
            logger.info(f"[promo_chat] Running 3 category-filtered searches: {granular_categories}")

            for category in granular_categories:
                # Build filter with category
                category_filter = {"granular_category": {"$eq": category}}
                combined_filter = {"$and": [base_filter, category_filter]}

                # Search with category filter
                hits = self._pinecone_search_and_rerank(search_query.search_text, combined_filter)

                for hit in hits:
                    hit_id = hit.get("_id", "")
                    if hit_id and hit_id in seen_ids:
                        continue
                    if hit_id:
                        seen_ids.add(hit_id)

                    score = hit.get("_score", 0)
                    # Threshold for category-filtered searches
                    if score >= 0.55:
                        promo = self._build_promo_result(hit.get("fields", {}), score)
                        if promo and self._is_valid_promo(promo) and not self._is_expired_promo(promo):
                            # Boost score if brand matches exactly
                            if search_query.brands and promo.brand:
                                if promo.brand.lower() in [b.lower() for b in search_query.brands]:
                                    promo.relevance_score = min(1.0, promo.relevance_score + 0.2)
                            all_promos.append(promo)

        # Also run a search without category filter as fallback
        logger.info(f"[promo_chat] Running fallback search without category filter")
        hits = self._pinecone_search_and_rerank(search_query.search_text, base_filter)

        for hit in hits:
            hit_id = hit.get("_id", "")
            if hit_id and hit_id in seen_ids:
                continue
            if hit_id:
                seen_ids.add(hit_id)

            score = hit.get("_score", 0)
            if score >= RERANK_SCORE_THRESHOLD:
                promo = self._build_promo_result(hit.get("fields", {}), score)
                if promo and self._is_valid_promo(promo) and not self._is_expired_promo(promo):
                    if search_query.brands and promo.brand:
                        if promo.brand.lower() in [b.lower() for b in search_query.brands]:
                            promo.relevance_score = min(1.0, promo.relevance_score + 0.2)
                    all_promos.append(promo)

        # Sort by relevance and limit results
        all_promos.sort(key=lambda p: p.relevance_score, reverse=True)
        return all_promos[:RERANK_TOP_N]

    def _pinecone_search_and_rerank(self, query_text: str, filter_dict: Optional[dict]) -> list[dict]:
        """Execute integrated search + rerank in a single Pinecone API call."""
        logger.info(f"[promo_chat] search: '{query_text}' filter={filter_dict}")

        query = {
            "inputs": {"text": query_text},
            "top_k": SEARCH_TOP_K,
        }
        if filter_dict:
            query["filter"] = filter_dict

        rerank = {
            "model": "bge-reranker-v2-m3",
            "rank_fields": ["text"],
            "top_n": RERANK_TOP_N,
        }

        try:
            results = self.index.search_records(namespace="__default__", query=query, rerank=rerank)
            return self._extract_hits(results)
        except (AttributeError, TypeError):
            try:
                results = self.index.search(namespace="__default__", query=query, rerank=rerank)
                return self._extract_hits(results)
            except Exception as e:
                logger.warning(f"Pinecone search failed: {e}")
                return []

    def _extract_hits(self, results) -> list[dict]:
        """Extract hits from Pinecone search response."""
        if hasattr(results, "result"):
            result = results.result
            if hasattr(result, "hits"):
                return [self._normalize_hit(h) for h in result.hits]

        if isinstance(results, dict):
            if "result" in results:
                return [self._normalize_hit(h) for h in results["result"].get("hits", [])]
            if "matches" in results:
                return [self._normalize_hit(m) for m in results["matches"]]

        if hasattr(results, "matches"):
            return [self._normalize_hit(m) for m in results.matches]

        return []

    def _normalize_hit(self, hit) -> dict:
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
            d["fields"] = dict(hit.fields) if not isinstance(hit.fields, dict) else hit.fields
        elif hasattr(hit, "metadata"):
            d["fields"] = dict(hit.metadata) if not isinstance(hit.metadata, dict) else hit.metadata
        else:
            d["fields"] = {}
        return d

    def _build_promo_result(self, fields: dict, score: float) -> Optional[PromoResult]:
        """Build a PromoResult from Pinecone fields."""
        try:
            original_price = None
            promo_price = None
            savings = None
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

            if original_price and promo_price and original_price > 0:
                savings = round(original_price - promo_price, 2)
                discount_percent = round((savings / original_price) * 100, 1)

            return PromoResult(
                product_name=fields.get("normalized_name", "Unknown"),
                original_description=fields.get("original_description", fields.get("normalized_name", "")),
                brand=fields.get("brand"),
                category=fields.get("granular_category", fields.get("parent_category", "Other")),
                original_price=original_price,
                promo_price=promo_price,
                savings=savings,
                discount_percent=discount_percent,
                promo_mechanism=fields.get("promo_mechanism"),
                unit_info=fields.get("unit_info"),
                retailer=fields.get("source_retailer", "Unknown"),
                validity_start=fields.get("validity_start"),
                validity_end=fields.get("validity_end"),
                relevance_score=round(score, 3),
            )
        except Exception as e:
            logger.warning(f"Failed to build promo result: {e}")
            return None

    def _is_valid_promo(self, promo: PromoResult) -> bool:
        """Check if a promo has valid pricing data."""
        if promo.original_price is not None and promo.promo_price is not None:
            if promo.original_price <= 0:
                return False
            if promo.promo_price > promo.original_price:
                return False
        return True

    @staticmethod
    def _is_expired_promo(promo: PromoResult) -> bool:
        """Safety net: check if promo is expired based on validity_end string."""
        if not promo.validity_end:
            return False
        try:
            end_date = datetime.strptime(promo.validity_end, "%Y-%m-%d").date()
            return end_date < date.today()
        except (ValueError, TypeError):
            return False

    def _build_success_response(self, search_query: SearchQuery, promos: list[PromoResult]) -> str:
        """Build a friendly response message for successful search."""
        num_promos = len(promos)
        retailers = list(set(p.retailer for p in promos if p.retailer))

        # Calculate total potential savings
        total_savings = sum(p.savings or 0 for p in promos)

        parts = []

        if search_query.brands:
            brand_str = ", ".join(search_query.brands)
            parts.append(f"I found {num_promos} promotion{'s' if num_promos != 1 else ''} for {brand_str}")
        elif search_query.product_keywords:
            keyword_str = ", ".join(search_query.product_keywords[:2])
            parts.append(f"I found {num_promos} promotion{'s' if num_promos != 1 else ''} for {keyword_str}")
        else:
            parts.append(f"I found {num_promos} matching promotion{'s' if num_promos != 1 else ''}")

        if retailers:
            if len(retailers) == 1:
                parts.append(f"at {retailers[0].title()}")
            else:
                parts.append(f"across {len(retailers)} stores")

        result = " ".join(parts) + "."

        if total_savings > 0:
            result += f" Total potential savings: EUR {total_savings:.2f}."

        return result

    def _build_no_results_response(self, search_query: SearchQuery) -> str:
        """Build a response when no promos are found."""
        if search_query.brands:
            return f"I couldn't find any current promotions for {', '.join(search_query.brands)}. Try searching for similar products or a broader category."
        elif search_query.retailers:
            return f"No matching promotions found at {', '.join(search_query.retailers)} right now. Try searching without the store filter or check back later."
        else:
            return "I couldn't find any promotions matching your search. Try being more specific about the product or brand you're looking for."

import logging
from datetime import date, timedelta
from typing import List, Optional, AsyncGenerator
from collections import defaultdict

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import GeminiAPIError
from app.models.transaction import Transaction
from app.schemas.chat import ChatMessage

settings = get_settings()
logger = logging.getLogger(__name__)


class DobbyChatServiceGemini:
    """Dobby AI chat service for answering questions about transactional data using Gemini."""

    MODEL = "gemini-2.0-flash"
    MAX_TOKENS = 4096

    SYSTEM_PROMPT = """You are Dobby, a witty and enthusiastic AI shopping buddy who LOVES diving into grocery data! Think of yourself as part financial advisor, part foodie friend, and part detective who gets genuinely excited about uncovering spending patterns.

YOUR PERSONALITY:
- Warm, playful, and genuinely curious about the user's habits
- Use casual language, light humor, and the occasional food pun when it fits naturally
- Celebrate wins ("Nice! You crushed your veggie game this month!")
- Be supportive, not judgmental, about spending choices
- Show genuine enthusiasm when you spot interesting patterns
- Keep responses conversational - like chatting with a clever friend, not reading a report

YOUR SUPERPOWERS:
1. Analyze spending patterns, totals, and trends with precision
2. Uncover surprising insights about shopping habits
3. Make data fun and digestible (pun intended)
4. Connect the dots between different spending categories
5. Offer genuinely useful tips based on what you see

GOLDEN RULES:
- NEVER say "I don't have enough data" or "I can't answer that" - instead, work with what you have! If asked about protein intake, look at Meat & Fish, Dairy & Eggs, etc. and give your best insight based on available data
- When you can't give a precise answer, pivot to related insights: "While I can't tell you exact calories, I can see you've been loading up on Fresh Produce lately - that's awesome for nutrients!"
- Always find SOMETHING helpful to say based on the data you have
- Be honest about what the data shows vs. what requires assumptions, but frame it positively
- All amounts are in EUR (€)
- When calculating totals, sum the item_price values (which already include quantity)
- Format numbers nicely (€123.45) and use bullet points for lists
- Categories: Meat & Fish, Alcohol, Drinks (Soft/Soda), Drinks (Water), Household, Snacks & Sweets, Fresh Produce, Dairy & Eggs, Ready Meals, Bakery, Pantry, Personal Care, Frozen, Baby & Kids, Pet Supplies, Other

RESPONSE STYLE:
- Start with the key insight or answer
- Add relevant context or interesting observations
- End with a helpful tip, fun observation, or follow-up question when appropriate
- Keep it punchy - no one wants to read an essay about their grocery bill

You will receive the user's transaction data as context. Use it to give them genuinely useful, entertaining insights!"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("Gemini API key not configured")
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(
            model_name=self.MODEL,
            system_instruction=self.SYSTEM_PROMPT,
        )

    async def _get_user_transaction_context(
        self,
        db: AsyncSession,
        user_id: str,
    ) -> str:
        """Build a context string with the user's transactional data."""
        today = date.today()

        # Get transactions from the last 12 months
        start_date = today - timedelta(days=365)

        result = await db.execute(
            select(Transaction).where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= start_date,
                )
            ).order_by(Transaction.date.desc())
        )
        transactions = list(result.scalars().all())

        if not transactions:
            return "No transaction data available for this user."

        # Build summary statistics
        total_spend = sum(t.item_price for t in transactions)
        transaction_count = len(transactions)

        # Get date range
        dates = [t.date for t in transactions]
        earliest_date = min(dates)
        latest_date = max(dates)

        # Calculate category breakdown
        category_totals = defaultdict(float)
        category_counts = defaultdict(int)
        for t in transactions:
            category_totals[t.category.value] += t.item_price
            category_counts[t.category.value] += 1

        # Calculate store breakdown
        store_totals = defaultdict(float)
        store_visits = defaultdict(set)
        for t in transactions:
            store_totals[t.store_name] += t.item_price
            store_visits[t.store_name].add(t.date)

        # Calculate monthly spending
        monthly_totals = defaultdict(float)
        for t in transactions:
            month_key = t.date.strftime("%Y-%m")
            monthly_totals[month_key] += t.item_price

        # Build context string
        context_parts = [
            "=== USER'S TRANSACTION DATA ===",
            f"\nData Range: {earliest_date} to {latest_date}",
            f"Total Transactions: {transaction_count}",
            f"Total Spending: €{total_spend:.2f}",
            f"\n--- SPENDING BY CATEGORY ---",
        ]

        # Sort categories by spending
        sorted_categories = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
        for category, amount in sorted_categories:
            count = category_counts[category]
            pct = (amount / total_spend * 100) if total_spend > 0 else 0
            context_parts.append(f"  {category}: €{amount:.2f} ({pct:.1f}%, {count} items)")

        context_parts.append(f"\n--- SPENDING BY STORE ---")
        sorted_stores = sorted(store_totals.items(), key=lambda x: x[1], reverse=True)
        for store, amount in sorted_stores:
            visits = len(store_visits[store])
            pct = (amount / total_spend * 100) if total_spend > 0 else 0
            context_parts.append(f"  {store}: €{amount:.2f} ({pct:.1f}%, {visits} visits)")

        context_parts.append(f"\n--- MONTHLY SPENDING ---")
        for month in sorted(monthly_totals.keys(), reverse=True)[:12]:
            context_parts.append(f"  {month}: €{monthly_totals[month]:.2f}")

        # Include recent transaction details (last 100)
        context_parts.append(f"\n--- RECENT TRANSACTIONS (Last 100) ---")
        for t in transactions[:100]:
            context_parts.append(
                f"  [{t.date}] {t.store_name} | {t.item_name} | €{t.item_price:.2f} | {t.category.value}"
            )

        return "\n".join(context_parts)

    async def chat(
        self,
        db: AsyncSession,
        user_id: str,
        message: str,
        conversation_history: Optional[List[ChatMessage]] = None,
    ) -> str:
        """
        Process a chat message and return a response (non-streaming).
        """
        try:
            # Get user's transaction context
            context = await self._get_user_transaction_context(db, user_id)

            # Build chat history for Gemini
            history = []

            # Add conversation history if provided
            if conversation_history:
                for msg in conversation_history:
                    role = "user" if msg.role == "user" else "model"
                    history.append({"role": role, "parts": [msg.content]})

            # Start chat with history
            chat = self.model.start_chat(history=history)

            # Build user message with context
            user_content = f"""Here is my transaction data:

{context}

My question: {message}"""

            # Call Gemini API
            response = chat.send_message(
                user_content,
                generation_config=genai.GenerationConfig(
                    max_output_tokens=self.MAX_TOKENS,
                    temperature=0.7,
                ),
            )

            return response.text

        except google_exceptions.InvalidArgument as e:
            logger.error(f"Gemini API invalid argument: {e}")
            raise GeminiAPIError(
                "Gemini API invalid argument - check request format",
                details={"error_type": "invalid_argument", "api_error": str(e)},
            )
        except google_exceptions.PermissionDenied as e:
            logger.error(f"Gemini API permission denied: {e}")
            raise GeminiAPIError(
                "Gemini API permission denied - invalid or missing API key",
                details={"error_type": "authentication", "api_error": str(e)},
            )
        except google_exceptions.ResourceExhausted as e:
            logger.warning(f"Gemini API rate limit exceeded: {e}")
            raise GeminiAPIError(
                "Gemini API rate limit exceeded - please retry later",
                details={"error_type": "rate_limit", "api_error": str(e)},
            )
        except google_exceptions.GoogleAPIError as e:
            logger.error(f"Gemini API error: {e}")
            raise GeminiAPIError(
                f"Gemini API error: {str(e)}",
                details={"error_type": "api_error", "api_error": str(e)},
            )

    async def chat_stream(
        self,
        db: AsyncSession,
        user_id: str,
        message: str,
        conversation_history: Optional[List[ChatMessage]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Process a chat message and stream the response.
        Yields text chunks as they are generated.
        """
        try:
            # Get user's transaction context
            context = await self._get_user_transaction_context(db, user_id)

            # Build chat history for Gemini
            history = []

            # Add conversation history if provided
            if conversation_history:
                for msg in conversation_history:
                    role = "user" if msg.role == "user" else "model"
                    history.append({"role": role, "parts": [msg.content]})

            # Start chat with history
            chat = self.model.start_chat(history=history)

            # Build user message with context
            user_content = f"""Here is my transaction data:

{context}

My question: {message}"""

            # Call Gemini API with streaming
            response = chat.send_message(
                user_content,
                generation_config=genai.GenerationConfig(
                    max_output_tokens=self.MAX_TOKENS,
                    temperature=0.7,
                ),
                stream=True,
            )

            for chunk in response:
                if chunk.text:
                    yield chunk.text

        except google_exceptions.InvalidArgument as e:
            logger.error(f"Gemini API invalid argument: {e}")
            raise GeminiAPIError(
                "Gemini API invalid argument - check request format",
                details={"error_type": "invalid_argument", "api_error": str(e)},
            )
        except google_exceptions.PermissionDenied as e:
            logger.error(f"Gemini API permission denied: {e}")
            raise GeminiAPIError(
                "Gemini API permission denied - invalid or missing API key",
                details={"error_type": "authentication", "api_error": str(e)},
            )
        except google_exceptions.ResourceExhausted as e:
            logger.warning(f"Gemini API rate limit exceeded: {e}")
            raise GeminiAPIError(
                "Gemini API rate limit exceeded - please retry later",
                details={"error_type": "rate_limit", "api_error": str(e)},
            )
        except google_exceptions.GoogleAPIError as e:
            logger.error(f"Gemini API error: {e}")
            raise GeminiAPIError(
                f"Gemini API error: {str(e)}",
                details={"error_type": "api_error", "api_error": str(e)},
            )

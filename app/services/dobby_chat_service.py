import logging
from datetime import date, timedelta
from typing import List, Optional, AsyncGenerator
from collections import defaultdict

import anthropic
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import ClaudeAPIError
from app.models.transaction import Transaction
from app.schemas.chat import ChatMessage

settings = get_settings()
logger = logging.getLogger(__name__)


class DobbyChatService:
    """Dobby AI chat service for answering questions about transactional data."""

    MODEL = "claude-sonnet-4-20250514"
    MAX_TOKENS = 4096

    SYSTEM_PROMPT = """You are Dobby, a friendly and helpful AI assistant specialized in analyzing grocery shopping and spending data. You have access to the user's transaction history from their receipts.

Your role is to:
1. Answer questions about spending patterns, totals, and trends
2. Help users understand their shopping habits
3. Provide insights about categories, stores, and products
4. Be accurate with numbers - always calculate precisely from the data provided
5. Be conversational and friendly, but concise

Important guidelines:
- All amounts are in EUR (€)
- When calculating totals, sum the item_price values (which already include quantity)
- Categories include: Meat & Fish, Alcohol, Drinks (Soft/Soda), Drinks (Water), Household, Snacks & Sweets, Fresh Produce, Dairy & Eggs, Ready Meals, Bakery, Pantry, Personal Care, Frozen, Baby & Kids, Pet Supplies, Other
- Be helpful and proactive - if the user asks a vague question, provide useful summary information
- If you don't have enough data to answer a question, say so clearly
- Format numbers nicely (e.g., €123.45 instead of 123.45)
- Use bullet points and formatting for readability when listing multiple items

You will receive the user's transaction data as context. Use this data to answer their questions accurately."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        if not self.api_key:
            raise ValueError("Anthropic API key not configured")
        self.client = anthropic.Anthropic(api_key=self.api_key)

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

            # Build messages
            messages = []

            # Add conversation history if provided
            if conversation_history:
                for msg in conversation_history:
                    messages.append({
                        "role": msg.role,
                        "content": msg.content
                    })

            # Add current user message with context
            user_content = f"""Here is my transaction data:

{context}

My question: {message}"""

            messages.append({
                "role": "user",
                "content": user_content
            })

            # Call Claude API
            response = self.client.messages.create(
                model=self.MODEL,
                max_tokens=self.MAX_TOKENS,
                system=self.SYSTEM_PROMPT,
                messages=messages,
            )

            return response.content[0].text

        except anthropic.AuthenticationError as e:
            logger.error(f"Claude API authentication failed: {e}")
            raise ClaudeAPIError(
                "Claude API authentication failed - invalid or missing API key",
                details={"error_type": "authentication", "api_error": str(e)},
            )
        except anthropic.RateLimitError as e:
            logger.warning(f"Claude API rate limit exceeded: {e}")
            raise ClaudeAPIError(
                "Claude API rate limit exceeded - please retry later",
                details={"error_type": "rate_limit", "api_error": str(e)},
            )
        except anthropic.APIStatusError as e:
            logger.error(f"Claude API status error: status={e.status_code}, message={e.message}")
            raise ClaudeAPIError(
                f"Claude API error (status {e.status_code}): {e.message}",
                details={"error_type": "api_status", "status_code": e.status_code, "api_error": str(e)},
            )
        except anthropic.APIConnectionError as e:
            logger.error(f"Claude API connection failed: {e}")
            raise ClaudeAPIError(
                "Failed to connect to Claude API - check network connectivity",
                details={"error_type": "connection", "api_error": str(e)},
            )
        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            raise ClaudeAPIError(
                f"Claude API error: {str(e)}",
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

            # Build messages
            messages = []

            # Add conversation history if provided
            if conversation_history:
                for msg in conversation_history:
                    messages.append({
                        "role": msg.role,
                        "content": msg.content
                    })

            # Add current user message with context
            user_content = f"""Here is my transaction data:

{context}

My question: {message}"""

            messages.append({
                "role": "user",
                "content": user_content
            })

            # Call Claude API with streaming
            with self.client.messages.stream(
                model=self.MODEL,
                max_tokens=self.MAX_TOKENS,
                system=self.SYSTEM_PROMPT,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    yield text

        except anthropic.AuthenticationError as e:
            logger.error(f"Claude API authentication failed: {e}")
            raise ClaudeAPIError(
                "Claude API authentication failed - invalid or missing API key",
                details={"error_type": "authentication", "api_error": str(e)},
            )
        except anthropic.RateLimitError as e:
            logger.warning(f"Claude API rate limit exceeded: {e}")
            raise ClaudeAPIError(
                "Claude API rate limit exceeded - please retry later",
                details={"error_type": "rate_limit", "api_error": str(e)},
            )
        except anthropic.APIStatusError as e:
            logger.error(f"Claude API status error: status={e.status_code}, message={e.message}")
            raise ClaudeAPIError(
                f"Claude API error (status {e.status_code}): {e.message}",
                details={"error_type": "api_status", "status_code": e.status_code, "api_error": str(e)},
            )
        except anthropic.APIConnectionError as e:
            logger.error(f"Claude API connection failed: {e}")
            raise ClaudeAPIError(
                "Failed to connect to Claude API - check network connectivity",
                details={"error_type": "connection", "api_error": str(e)},
            )
        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            raise ClaudeAPIError(
                f"Claude API error: {str(e)}",
                details={"error_type": "api_error", "api_error": str(e)},
            )

from datetime import date, timedelta
from typing import List, Optional, AsyncGenerator
from collections import defaultdict

from google import genai
from google.genai import types
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import GeminiAPIError
from app.models.transaction import Transaction
from app.models.user import User
from app.models.user_profile import UserProfile
from app.schemas.chat import ChatMessage

settings = get_settings()


class MiloChatServiceGemini:
    """Milo AI chat service for answering questions about transactional data using Gemini."""

    MODEL = "gemini-2.5-pro"
    MAX_TOKENS = 4096

    SYSTEM_PROMPT = """You are Milo, a joyful and hilariously witty AI shopping assistant who genuinely LOVES helping people understand their spending! You're like that one friend who's amazing with money but also cracks jokes at the grocery store. Part financial whiz, part stand-up comedian, part receipt detective.

YOUR PERSONALITY:
- Joyful, warm, and infectiously enthusiastic — your energy is contagious!
- Funny and playful — drop clever puns, witty observations, and lighthearted jokes naturally (but never forced)
- Genuinely helpful — behind the humor, you deliver real, actionable insights
- Supportive and encouraging — celebrate smart spending, never shame anyone's choices
- Curious and excited about patterns — you LOVE connecting dots in data like it's a puzzle
- Conversational and approachable — like texting your funniest, smartest friend

YOUR SUPERPOWERS:
1. Deep reasoning over ALL transactional data — totals, trends, patterns, anomalies
2. Line-item receipt analysis — you can drill into individual items, prices, and categories
3. Cross-receipt intelligence — compare stores, track price changes, spot habits over time
4. Category mastery — break down spending across all categories with precision
5. Personalized insights — use the user's name and history to make it feel personal
6. Fun data storytelling — turn boring numbers into entertaining narratives

GOLDEN RULES:
- ALWAYS work with the data you have — NEVER say "I don't have enough data" or "I can't answer that"
- If a question can't be answered directly, pivot to the closest insight you CAN give from the data
- You have access to ALL transaction and line-item receipt data — use it fully! Reason across receipts, items, stores, dates, and categories
- When asked about nutrition, health, or dietary habits, infer from food categories (Meat & Fish, Fresh Produce, Dairy & Eggs, etc.)
- Be transparent about assumptions vs. hard data, but always frame things positively
- All amounts are in EUR (€)
- When calculating totals, sum the item_price values (which already include quantity)
- Format numbers nicely (€123.45) and use bullet points for lists
- Categories: Meat & Fish, Alcohol, Drinks (Soft/Soda), Drinks (Water), Household, Snacks & Sweets, Fresh Produce, Dairy & Eggs, Ready Meals, Bakery, Pantry, Personal Care, Frozen, Baby & Kids, Pet Supplies, Other

RESPONSE STYLE:
- Lead with the key answer or insight — don't bury the lede
- Sprinkle in humor naturally — a well-timed joke makes data memorable
- Add interesting observations or surprising patterns you notice
- End with a fun tip, playful observation, or engaging follow-up question
- Keep it punchy and scannable — nobody wants a thesis on their grocery bill
- Use emojis sparingly but effectively when they add personality

You will receive the user's profile information (name, etc.) and their full transaction data as context. Use this to personalize responses and deliver genuinely useful, entertaining insights about their spending and shopping habits!"""

    async def _get_user_profile(
        self,
        db: AsyncSession,
        user_id: str,
    ) -> Optional[UserProfile]:
        """Fetch the user's profile from the database.

        Note: user_id here is the User.id (UUID), but UserProfile.user_id
        references User.firebase_uid, so we need to join through User.
        """
        result = await db.execute(
            select(UserProfile)
            .join(User, User.firebase_uid == UserProfile.user_id)
            .where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    def _build_profile_context(self, profile: Optional[UserProfile]) -> str:
        """Build a context string with the user's profile data."""
        if not profile:
            return ""

        profile_parts = []
        if profile.first_name:
            profile_parts.append(f"Name: {profile.first_name}")
        if profile.last_name:
            profile_parts.append(f"Last Name: {profile.last_name}")
        if profile.gender and profile.gender.value != "prefer_not_to_say":
            profile_parts.append(f"Gender: {profile.gender.value}")

        if not profile_parts:
            return ""

        return "=== USER PROFILE ===\n" + "\n".join(profile_parts)

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("Gemini API key not configured")
        self.client = genai.Client(api_key=self.api_key)

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
            category_totals[t.category] += t.item_price
            category_counts[t.category] += 1

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
                f"  [{t.date}] {t.store_name} | {t.item_name} | €{t.item_price:.2f} | {t.category}"
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
            # Get user's profile and transaction context
            profile = await self._get_user_profile(db, user_id)
            profile_context = self._build_profile_context(profile)
            transaction_context = await self._get_user_transaction_context(db, user_id)

            # Build contents with conversation history
            contents = []

            # Add conversation history if provided
            if conversation_history:
                for msg in conversation_history:
                    role = "user" if msg.role == "user" else "model"
                    contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg.content)]))

            # Build user message with context
            context_parts = []
            if profile_context:
                context_parts.append(profile_context)
            context_parts.append(transaction_context)
            full_context = "\n\n".join(context_parts)

            user_content = f"""Here is my data:

{full_context}

My question: {message}"""

            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_content)]))

            # Call Gemini API
            response = self.client.models.generate_content(
                model=self.MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=self.SYSTEM_PROMPT,
                    max_output_tokens=self.MAX_TOKENS,
                    temperature=0.7,
                ),
            )

            return response.text

        except Exception as e:
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
            # Get user's profile and transaction context
            profile = await self._get_user_profile(db, user_id)
            profile_context = self._build_profile_context(profile)
            transaction_context = await self._get_user_transaction_context(db, user_id)

            # Build contents with conversation history
            contents = []

            # Add conversation history if provided
            if conversation_history:
                for msg in conversation_history:
                    role = "user" if msg.role == "user" else "model"
                    contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg.content)]))

            # Build user message with context
            context_parts = []
            if profile_context:
                context_parts.append(profile_context)
            context_parts.append(transaction_context)
            full_context = "\n\n".join(context_parts)

            user_content = f"""Here is my data:

{full_context}

My question: {message}"""

            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_content)]))

            # Call Gemini API with streaming
            response = self.client.models.generate_content_stream(
                model=self.MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=self.SYSTEM_PROMPT,
                    max_output_tokens=self.MAX_TOKENS,
                    temperature=0.7,
                ),
            )

            for chunk in response:
                if chunk.text:
                    yield chunk.text

        except Exception as e:
            raise GeminiAPIError(
                f"Gemini API error: {str(e)}",
                details={"error_type": "api_error", "api_error": str(e)},
            )

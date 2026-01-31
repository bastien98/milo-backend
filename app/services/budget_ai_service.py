import json
import logging
import re
import calendar
from datetime import date, timedelta
from typing import Optional, Any
from collections import defaultdict

from google import genai
from google.genai import types
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import GeminiAPIError
from app.models.transaction import Transaction
from app.models.receipt import Receipt
from app.models.budget import Budget
from app.schemas.budget_ai import (
    AIBudgetSuggestionResponse,
    RecommendedBudget,
    CategoryAllocationSuggestion,
    SavingsOpportunity,
    SpendingInsight,
    AICheckInResponse,
    StatusSummary,
    ProjectedEndOfMonth,
    FocusArea,
    AIReceiptAnalysisResponse,
    NotableItem,
    AIMonthlyReportResponse,
    CategoryGrade,
    TrendItem,
    NextMonthFocus,
)

settings = get_settings()
logger = logging.getLogger(__name__)


class BudgetAIService:
    """AI-powered budget analysis service using Gemini."""

    MODEL = "gemini-2.0-flash"
    MAX_TOKENS = 4096

    # =========================================================================
    # System Prompts
    # =========================================================================

    SUGGESTION_SYSTEM_PROMPT = """You are a friendly, encouraging personal finance coach analyzing grocery spending for budget optimization.

YOUR PERSONALITY:
- Warm, supportive, and genuinely helpful
- Use casual language and be encouraging
- Celebrate good habits, be supportive about areas for improvement
- Never judgmental about spending choices
- Focus on actionable, specific advice

YOUR TASK:
Analyze the spending data and provide personalized budget recommendations.

IMPORTANT GUIDELINES:
- All amounts in EUR (€)
- Reference actual numbers from their data
- Be specific - generic advice is not helpful
- Consider Belgian grocery stores and habits
- Round budget suggestions to nearest €5

CRITICAL - CATEGORY ALLOCATIONS:
- You MUST include an allocation for EVERY category listed in the user's spending data
- Do NOT skip any categories, even if they have small amounts
- Include ALL categories the user has spent money on
- Sort allocations by suggested_amount descending (highest first)
- The sum of all category allocations should equal the recommended budget amount

Return ONLY valid JSON with this exact structure:
{
    "recommended_budget": {
        "amount": <number>,
        "confidence": "high" | "medium" | "low",
        "reasoning": "<why this amount>"
    },
    "category_allocations": [
        {
            "category": "<category name>",
            "suggested_amount": <number>,
            "percentage": <number>,
            "insight": "<why this allocation>",
            "savings_potential": "high" | "medium" | "low" | "none"
        }
    ],
    "savings_opportunities": [
        {
            "title": "<short title>",
            "description": "<actionable advice>",
            "potential_savings": <number>,
            "difficulty": "easy" | "medium" | "hard"
        }
    ],
    "spending_insights": [
        {
            "type": "pattern" | "trend" | "anomaly" | "positive",
            "title": "<insight title>",
            "description": "<what you noticed>",
            "recommendation": "<what to do about it>"
        }
    ],
    "personalized_tips": ["<tip 1>", "<tip 2>", "<tip 3>"],
    "budget_health_score": <1-100>,
    "summary": "<2-3 sentence personalized summary>"
}"""

    SUGGESTION_WITH_TARGET_SYSTEM_PROMPT = """You are a friendly, encouraging personal finance coach analyzing grocery spending for budget optimization.

YOUR PERSONALITY:
- Warm, supportive, and genuinely helpful
- Use casual language and be encouraging
- Celebrate good habits, be supportive about areas for improvement
- Never judgmental about spending choices
- Focus on actionable, specific advice

YOUR TASK:
The user has requested a SPECIFIC TARGET BUDGET AMOUNT. You must intelligently allocate their spending across categories to fit this target.

CRITICAL ALLOCATION RULES:
1. You MUST include an allocation for EVERY category listed in the user's spending data - do NOT skip any categories
2. Category allocations MUST sum EXACTLY to the target amount
3. DO NOT just scale proportionally - be intelligent about where to cut
4. Prioritize cuts in this order:
   - HIGH savings potential: Alcohol, Tobacco, Snacks & Sweets, Ready Meals
   - MEDIUM savings potential: Drinks (Soft/Soda), Frozen, Household, Personal Care
   - LOW savings potential (preserve these): Fresh Produce, Dairy & Eggs, Meat & Fish, Bakery, Pantry
5. Consider the user's actual spending patterns when deciding realistic cuts
6. Never reduce essential categories below realistic minimums
7. If the target is unrealistically low, still provide allocations but reflect this in the health score
8. Sort allocations by suggested_amount descending (highest first)

BUDGET HEALTH SCORE GUIDELINES (when target_amount is provided):
- 80-100: Target is easily achievable with minor adjustments
- 60-79: Target is achievable but requires meaningful lifestyle changes
- 40-59: Target is challenging and may require significant sacrifices
- 20-39: Target is very difficult, may compromise nutrition/essentials
- 1-19: Target is unrealistic given current spending patterns

IMPORTANT GUIDELINES:
- All amounts in EUR (€)
- Reference actual numbers from their data
- Be specific - generic advice is not helpful
- Consider Belgian grocery stores and habits
- Round category allocations to nearest €5

Return ONLY valid JSON with this exact structure:
{
    "recommended_budget": {
        "amount": <the target amount requested>,
        "confidence": "high" | "medium" | "low",
        "reasoning": "<why this target is/isn't achievable>"
    },
    "allocation_strategy": "<1-2 sentences explaining HOW you allocated the budget to meet the target, e.g. 'Reduced alcohol and snacks by 30% while maintaining fresh produce budget'>",
    "category_allocations": [
        {
            "category": "<category name>",
            "suggested_amount": <number - MUST sum to target>,
            "percentage": <number>,
            "insight": "<why this allocation, what was changed from current spending>",
            "savings_potential": "high" | "medium" | "low" | "none"
        }
    ],
    "savings_opportunities": [
        {
            "title": "<short title>",
            "description": "<actionable advice for achieving this target>",
            "potential_savings": <number>,
            "difficulty": "easy" | "medium" | "hard"
        }
    ],
    "spending_insights": [
        {
            "type": "pattern" | "trend" | "anomaly" | "positive",
            "title": "<insight title>",
            "description": "<what you noticed>",
            "recommendation": "<what to do about it>"
        }
    ],
    "personalized_tips": ["<tip 1>", "<tip 2>", "<tip 3>"],
    "budget_health_score": <1-100, reflecting achievability of target>,
    "summary": "<2-3 sentence summary focused on achieving the target budget>"
}"""

    CHECKIN_SYSTEM_PROMPT = """You are Dobby, a friendly and witty budget buddy providing a weekly check-in.

YOUR PERSONALITY:
- Warm, playful, and genuinely supportive
- Use casual language and light humor
- Celebrate wins enthusiastically
- Be supportive about challenges, never judgmental
- Keep it conversational and brief

YOUR TASK:
Provide a warm, encouraging check-in based on the user's current budget progress.

IMPORTANT GUIDELINES:
- All amounts in EUR (€)
- Reference actual numbers from their data
- Keep messages short and punchy
- Maximum 3 focus areas
- Make tips specific and actionable

Return ONLY valid JSON with this exact structure:
{
    "greeting": "<personalized greeting based on status>",
    "status_summary": {
        "emoji": "<appropriate emoji>",
        "headline": "<short status headline>",
        "detail": "<1-2 sentence explanation>"
    },
    "daily_budget_remaining": <number>,
    "projected_end_of_month": {
        "amount": <number>,
        "status": "under_budget" | "on_track" | "over_budget",
        "message": "<what this means>"
    },
    "focus_areas": [
        {
            "category": "<category name>",
            "status": "good" | "warning" | "critical",
            "message": "<specific advice>"
        }
    ],
    "weekly_tip": "<one actionable tip for next week>",
    "motivation": "<encouraging message>"
}"""

    RECEIPT_ANALYSIS_SYSTEM_PROMPT = """You are a quick budget assistant providing instant feedback on a scanned receipt.

YOUR PERSONALITY:
- Brief, helpful, and non-judgmental
- Use emojis sparingly but appropriately
- Focus on impact, not criticism

YOUR TASK:
Analyze this receipt in the context of the user's budget and provide quick feedback.

IMPORTANT GUIDELINES:
- All amounts in EUR (€)
- Keep it very brief - this appears right after scanning
- Be supportive, not critical
- Only mention notable items if truly relevant

Return ONLY valid JSON with this exact structure:
{
    "impact_summary": "<one line about how this affects budget>",
    "emoji": "<appropriate emoji like 🟢, 🟡, or 🔴>",
    "status": "great" | "fine" | "caution" | "warning",
    "notable_items": [
        {
            "item": "<item name>",
            "observation": "<quick note - expensive, good deal, impulse buy, etc.>"
        }
    ],
    "quick_tip": "<optional - only if relevant, otherwise null>"
}"""

    MONTHLY_REPORT_SYSTEM_PROMPT = """You are a thoughtful personal finance coach generating a comprehensive monthly budget report.

YOUR PERSONALITY:
- Encouraging while honest
- Celebrate progress, provide constructive feedback
- Use engaging language and light humor where appropriate
- Make it feel like a personal review, not a cold report

YOUR TASK:
Generate a comprehensive, personalized monthly report.

IMPORTANT GUIDELINES:
- All amounts in EUR (€)
- Reference actual numbers from their data
- Be specific with wins and challenges
- Include at least 2-3 fun stats
- Grades should be fair but encouraging

Return ONLY valid JSON with this exact structure:
{
    "headline": "<catchy summary of the month>",
    "grade": "A+" | "A" | "B" | "C" | "D" | "F",
    "score": <1-100>,
    "wins": ["<specific achievement>", "<another achievement>"],
    "challenges": ["<specific challenge>"],
    "category_grades": [
        {
            "category": "<name>",
            "grade": "A+" | "A" | "B" | "C" | "D" | "F",
            "spent": <amount>,
            "budget": <amount>,
            "comment": "<brief comment>"
        }
    ],
    "trends": [
        {
            "type": "improving" | "declining" | "stable",
            "area": "<what's trending>",
            "detail": "<explanation>"
        }
    ],
    "next_month_focus": {
        "primary_goal": "<main thing to focus on>",
        "suggested_budget_adjustment": <number or null>,
        "reason": "<why this adjustment>"
    },
    "fun_stats": ["<interesting stat>", "<another interesting stat>"]
}"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("Gemini API key not configured")
        self.client = genai.Client(api_key=self.api_key)

    # =========================================================================
    # Main Methods
    # =========================================================================

    async def generate_budget_suggestion(
        self,
        db: AsyncSession,
        user_id: str,
        months: int = 3,
        target_amount: Optional[float] = None,
    ) -> AIBudgetSuggestionResponse:
        """Generate AI-powered budget recommendation.

        Args:
            db: Database session
            user_id: User ID
            months: Number of months to analyze
            target_amount: Optional target budget amount. When provided, AI will
                intelligently allocate categories to fit this budget.
        """
        try:
            # Gather spending data
            spending_data = await self._gather_spending_data(db, user_id, months)

            if not spending_data["transactions"]:
                raise GeminiAPIError(
                    "No spending data available",
                    details={"error_type": "no_data"},
                )

            # Build prompt (with optional target_amount context)
            prompt = self._build_suggestion_prompt(spending_data, target_amount)

            # Use different system prompt based on whether target_amount is provided
            system_prompt = (
                self.SUGGESTION_WITH_TARGET_SYSTEM_PROMPT
                if target_amount is not None
                else self.SUGGESTION_SYSTEM_PROMPT
            )

            # Call Gemini
            response = self._call_gemini(prompt, system_prompt)

            # Parse response
            ai_data = self._extract_json(response)

            return AIBudgetSuggestionResponse(
                recommended_budget=RecommendedBudget(**ai_data["recommended_budget"]),
                category_allocations=[
                    CategoryAllocationSuggestion(**cat)
                    for cat in ai_data["category_allocations"]
                ],
                savings_opportunities=[
                    SavingsOpportunity(**opp)
                    for opp in ai_data["savings_opportunities"]
                ],
                spending_insights=[
                    SpendingInsight(**insight)
                    for insight in ai_data["spending_insights"]
                ],
                personalized_tips=ai_data["personalized_tips"],
                budget_health_score=ai_data["budget_health_score"],
                summary=ai_data["summary"],
                based_on_months=months,
                total_spend_analyzed=spending_data["total_spend"],
                cached_at=None,
                # Include target-based fields when target_amount was provided
                target_amount=target_amount,
                allocation_strategy=ai_data.get("allocation_strategy"),
            )

        except GeminiAPIError:
            raise
        except Exception as e:
            logger.exception(f"Error generating budget suggestion: {e}")
            raise GeminiAPIError(
                f"Failed to generate budget suggestion: {str(e)}",
                details={"error_type": "generation_error"},
            )

    async def generate_checkin(
        self,
        db: AsyncSession,
        user_id: str,
    ) -> AICheckInResponse:
        """Generate weekly AI check-in."""
        try:
            # Gather progress data
            progress_data = await self._gather_budget_progress(db, user_id)

            if not progress_data["budget"]:
                raise GeminiAPIError(
                    "No budget set",
                    details={"error_type": "no_budget"},
                )

            # Build prompt
            prompt = self._build_checkin_prompt(progress_data)

            # Call Gemini
            response = self._call_gemini(prompt, self.CHECKIN_SYSTEM_PROMPT)

            # Parse response
            ai_data = self._extract_json(response)

            return AICheckInResponse(
                greeting=ai_data["greeting"],
                status_summary=StatusSummary(**ai_data["status_summary"]),
                daily_budget_remaining=ai_data["daily_budget_remaining"],
                projected_end_of_month=ProjectedEndOfMonth(
                    **ai_data["projected_end_of_month"]
                ),
                focus_areas=[FocusArea(**area) for area in ai_data["focus_areas"]],
                weekly_tip=ai_data["weekly_tip"],
                motivation=ai_data["motivation"],
                days_remaining=progress_data["days_remaining"],
                current_spend=progress_data["current_spend"],
                budget_amount=progress_data["budget"]["monthly_amount"],
            )

        except GeminiAPIError:
            raise
        except Exception as e:
            logger.exception(f"Error generating check-in: {e}")
            raise GeminiAPIError(
                f"Failed to generate check-in: {str(e)}",
                details={"error_type": "generation_error"},
            )

    async def analyze_receipt(
        self,
        db: AsyncSession,
        user_id: str,
        receipt_id: str,
    ) -> AIReceiptAnalysisResponse:
        """Analyze a receipt for budget impact."""
        try:
            # Gather receipt context
            receipt_context = await self._gather_receipt_context(
                db, user_id, receipt_id
            )

            if not receipt_context["receipt"]:
                raise GeminiAPIError(
                    "Receipt not found",
                    details={"error_type": "not_found"},
                )

            # Build prompt
            prompt = self._build_receipt_prompt(receipt_context)

            # Call Gemini
            response = self._call_gemini(prompt, self.RECEIPT_ANALYSIS_SYSTEM_PROMPT)

            # Parse response
            ai_data = self._extract_json(response)

            return AIReceiptAnalysisResponse(
                impact_summary=ai_data["impact_summary"],
                emoji=ai_data["emoji"],
                status=ai_data["status"],
                notable_items=[
                    NotableItem(**item) for item in ai_data.get("notable_items", [])
                ],
                quick_tip=ai_data.get("quick_tip"),
                receipt_total=receipt_context["receipt_total"],
                budget_remaining_after=receipt_context["budget_remaining_after"],
                percentage_used_after=receipt_context["percentage_used_after"],
            )

        except GeminiAPIError:
            raise
        except Exception as e:
            logger.exception(f"Error analyzing receipt: {e}")
            raise GeminiAPIError(
                f"Failed to analyze receipt: {str(e)}",
                details={"error_type": "generation_error"},
            )

    async def generate_monthly_report(
        self,
        db: AsyncSession,
        user_id: str,
        month: str,
    ) -> AIMonthlyReportResponse:
        """Generate end-of-month AI report."""
        try:
            # Gather monthly data
            monthly_data = await self._gather_monthly_data(db, user_id, month)

            if not monthly_data["receipts"]:
                raise GeminiAPIError(
                    "No receipts found for this month",
                    details={"error_type": "no_data"},
                )

            # Build prompt
            prompt = self._build_monthly_report_prompt(monthly_data)

            # Call Gemini
            response = self._call_gemini(prompt, self.MONTHLY_REPORT_SYSTEM_PROMPT)

            # Parse response
            ai_data = self._extract_json(response)

            return AIMonthlyReportResponse(
                headline=ai_data["headline"],
                grade=ai_data["grade"],
                score=ai_data["score"],
                wins=ai_data["wins"],
                challenges=ai_data["challenges"],
                category_grades=[
                    CategoryGrade(**grade) for grade in ai_data["category_grades"]
                ],
                trends=[TrendItem(**trend) for trend in ai_data["trends"]],
                next_month_focus=NextMonthFocus(**ai_data["next_month_focus"]),
                fun_stats=ai_data["fun_stats"],
                month=month,
                total_spent=monthly_data["total_spent"],
                budget_amount=monthly_data["budget_amount"],
                receipt_count=len(monthly_data["receipts"]),
            )

        except GeminiAPIError:
            raise
        except Exception as e:
            logger.exception(f"Error generating monthly report: {e}")
            raise GeminiAPIError(
                f"Failed to generate monthly report: {str(e)}",
                details={"error_type": "generation_error"},
            )

    # =========================================================================
    # Data Gathering Helpers
    # =========================================================================

    async def _gather_spending_data(
        self,
        db: AsyncSession,
        user_id: str,
        months: int,
    ) -> dict:
        """Gather comprehensive spending data for AI analysis.

        Includes data from the current month plus previous complete months.
        """
        today = date.today()

        # Include current month's data (up to today)
        end_date = today + timedelta(days=1)  # Tomorrow (to include today)

        # Calculate start date: go back N months from current month
        year = today.year
        month = today.month - months + 1  # +1 to include current month
        while month <= 0:
            month += 12
            year -= 1
        start_date = date(year, month, 1)

        # Query transactions
        result = await db.execute(
            select(Transaction)
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= start_date,
                    Transaction.date < end_date,
                )
            )
            .order_by(Transaction.date.desc())
        )
        transactions = list(result.scalars().all())

        if not transactions:
            return {"transactions": [], "total_spend": 0}

        # Calculate aggregations
        total_spend = sum(t.item_price for t in transactions)

        # By category
        by_category = defaultdict(lambda: {"total": 0, "count": 0, "items": []})
        for t in transactions:
            cat = t.category.value
            by_category[cat]["total"] += t.item_price
            by_category[cat]["count"] += 1
            if len(by_category[cat]["items"]) < 5:
                by_category[cat]["items"].append(t.item_name)

        # By week
        by_week = defaultdict(float)
        for t in transactions:
            week_key = t.date.strftime("%Y-W%W")
            by_week[week_key] += t.item_price

        # By store
        by_store = defaultdict(lambda: {"total": 0, "visits": set()})
        for t in transactions:
            by_store[t.store_name]["total"] += t.item_price
            by_store[t.store_name]["visits"].add(t.date)

        # By day of week
        by_day = defaultdict(float)
        day_names = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        for t in transactions:
            by_day[day_names[t.date.weekday()]] += t.item_price

        # Monthly averages
        monthly_totals = defaultdict(float)
        for t in transactions:
            month_key = t.date.strftime("%Y-%m")
            monthly_totals[month_key] += t.item_price

        return {
            "transactions": transactions,
            "total_spend": total_spend,
            "months_analyzed": months,
            "monthly_average": total_spend / max(len(monthly_totals), 1),
            "by_category": dict(by_category),
            "by_week": dict(by_week),
            "by_store": {k: {"total": v["total"], "visits": len(v["visits"])} for k, v in by_store.items()},
            "by_day_of_week": dict(by_day),
            "monthly_totals": dict(monthly_totals),
            "receipt_count": len(set(t.receipt_id for t in transactions if t.receipt_id)),
        }

    async def _gather_budget_progress(
        self,
        db: AsyncSession,
        user_id: str,
    ) -> dict:
        """Gather current budget progress data."""
        today = date.today()
        first_day = today.replace(day=1)
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        days_elapsed = today.day
        days_remaining = days_in_month - days_elapsed

        # Get budget
        budget_result = await db.execute(
            select(Budget).where(Budget.user_id == user_id)
        )
        budget = budget_result.scalar_one_or_none()

        if not budget:
            return {"budget": None}

        # Get current month spending
        spend_result = await db.execute(
            select(func.coalesce(func.sum(Transaction.item_price), 0)).where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= first_day,
                    Transaction.date <= today,
                )
            )
        )
        current_spend = float(spend_result.scalar() or 0)

        # Get spending by category
        cat_result = await db.execute(
            select(
                Transaction.category,
                func.sum(Transaction.item_price).label("spent"),
            )
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= first_day,
                    Transaction.date <= today,
                )
            )
            .group_by(Transaction.category)
        )
        spend_by_category = {row.category.value: float(row.spent) for row in cat_result.all()}

        # Get last 7 days spending
        week_ago = today - timedelta(days=7)
        recent_result = await db.execute(
            select(Transaction)
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= week_ago,
                    Transaction.date <= today,
                )
            )
            .order_by(Transaction.date.desc())
        )
        recent_transactions = list(recent_result.scalars().all())
        recent_spend = sum(t.item_price for t in recent_transactions)

        # Get same period last month
        last_month = today.replace(day=1) - timedelta(days=1)
        last_month_start = last_month.replace(day=1)
        last_month_same_day = min(days_elapsed, calendar.monthrange(last_month.year, last_month.month)[1])
        last_month_end = last_month_start.replace(day=last_month_same_day)

        last_month_result = await db.execute(
            select(func.coalesce(func.sum(Transaction.item_price), 0)).where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= last_month_start,
                    Transaction.date <= last_month_end,
                )
            )
        )
        last_month_same_period = float(last_month_result.scalar() or 0)

        return {
            "budget": {
                "monthly_amount": budget.monthly_amount,
                "category_allocations": budget.category_allocations,
            },
            "current_spend": current_spend,
            "spend_by_category": spend_by_category,
            "days_elapsed": days_elapsed,
            "days_remaining": days_remaining,
            "days_in_month": days_in_month,
            "recent_spend": recent_spend,
            "recent_transactions": recent_transactions[:20],
            "last_month_same_period": last_month_same_period,
        }

    async def _gather_receipt_context(
        self,
        db: AsyncSession,
        user_id: str,
        receipt_id: str,
    ) -> dict:
        """Gather context for receipt analysis."""
        today = date.today()
        first_day = today.replace(day=1)

        # Get receipt
        receipt_result = await db.execute(
            select(Receipt).where(
                and_(Receipt.id == receipt_id, Receipt.user_id == user_id)
            )
        )
        receipt = receipt_result.scalar_one_or_none()

        if not receipt:
            return {"receipt": None}

        # Get receipt items (transactions)
        items_result = await db.execute(
            select(Transaction).where(Transaction.receipt_id == receipt_id)
        )
        items = list(items_result.scalars().all())

        # Get budget
        budget_result = await db.execute(
            select(Budget).where(Budget.user_id == user_id)
        )
        budget = budget_result.scalar_one_or_none()

        # Get current month spending (before this receipt)
        spend_result = await db.execute(
            select(func.coalesce(func.sum(Transaction.item_price), 0)).where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= first_day,
                    Transaction.date <= today,
                    Transaction.receipt_id != receipt_id,
                )
            )
        )
        spend_before = float(spend_result.scalar() or 0)

        receipt_total = receipt.total_amount or sum(i.item_price for i in items)
        budget_amount = budget.monthly_amount if budget else 0
        spend_after = spend_before + receipt_total

        return {
            "receipt": receipt,
            "items": items,
            "receipt_total": receipt_total,
            "store_name": receipt.store_name,
            "budget_amount": budget_amount,
            "spend_before": spend_before,
            "spend_after": spend_after,
            "budget_remaining_after": max(0, budget_amount - spend_after),
            "percentage_used_after": (spend_after / budget_amount * 100) if budget_amount > 0 else 0,
            "days_remaining": calendar.monthrange(today.year, today.month)[1] - today.day,
        }

    async def _gather_monthly_data(
        self,
        db: AsyncSession,
        user_id: str,
        month: str,
    ) -> dict:
        """Gather data for monthly report."""
        # Parse month
        year, month_num = map(int, month.split("-"))
        start_date = date(year, month_num, 1)
        days_in_month = calendar.monthrange(year, month_num)[1]
        end_date = date(year, month_num, days_in_month)

        # Get receipts
        receipts_result = await db.execute(
            select(Receipt).where(
                and_(
                    Receipt.user_id == user_id,
                    Receipt.receipt_date >= start_date,
                    Receipt.receipt_date <= end_date,
                )
            )
        )
        receipts = list(receipts_result.scalars().all())

        # Get transactions
        transactions_result = await db.execute(
            select(Transaction).where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.date >= start_date,
                    Transaction.date <= end_date,
                )
            )
        )
        transactions = list(transactions_result.scalars().all())

        # Get budget
        budget_result = await db.execute(
            select(Budget).where(Budget.user_id == user_id)
        )
        budget = budget_result.scalar_one_or_none()

        # Calculate totals
        total_spent = sum(t.item_price for t in transactions)

        # By category
        by_category = defaultdict(lambda: {"total": 0, "count": 0})
        for t in transactions:
            by_category[t.category.value]["total"] += t.item_price
            by_category[t.category.value]["count"] += 1

        # By store
        by_store = defaultdict(float)
        for t in transactions:
            by_store[t.store_name] += t.item_price

        # Get previous months for comparison
        prev_months = []
        for i in range(1, 4):
            prev_month = month_num - i
            prev_year = year
            while prev_month <= 0:
                prev_month += 12
                prev_year -= 1
            prev_start = date(prev_year, prev_month, 1)
            prev_days = calendar.monthrange(prev_year, prev_month)[1]
            prev_end = date(prev_year, prev_month, prev_days)

            prev_result = await db.execute(
                select(func.coalesce(func.sum(Transaction.item_price), 0)).where(
                    and_(
                        Transaction.user_id == user_id,
                        Transaction.date >= prev_start,
                        Transaction.date <= prev_end,
                    )
                )
            )
            prev_months.append({
                "month": f"{prev_year}-{prev_month:02d}",
                "total": float(prev_result.scalar() or 0),
            })

        # Top items
        item_counts = defaultdict(int)
        for t in transactions:
            item_counts[t.item_name] += 1
        top_items = sorted(item_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "month": month,
            "receipts": receipts,
            "transactions": transactions,
            "total_spent": total_spent,
            "budget_amount": budget.monthly_amount if budget else 0,
            "by_category": dict(by_category),
            "by_store": dict(by_store),
            "previous_months": prev_months,
            "top_items": top_items,
            "receipt_count": len(receipts),
        }

    # =========================================================================
    # Prompt Building Helpers
    # =========================================================================

    def _build_suggestion_prompt(
        self, spending_data: dict, target_amount: Optional[float] = None
    ) -> str:
        """Build prompt for budget suggestion.

        Args:
            spending_data: Aggregated spending data
            target_amount: Optional target budget amount for constrained allocation
        """
        lines = [
            f"## User Spending Data (Last {spending_data['months_analyzed']} Months)",
            "",
            f"**Total Spend:** €{spending_data['total_spend']:.2f}",
            f"**Monthly Average:** €{spending_data['monthly_average']:.2f}",
            f"**Number of Receipts:** {spending_data['receipt_count']}",
        ]

        # Add target amount context if provided
        if target_amount is not None:
            savings_needed = spending_data["monthly_average"] - target_amount
            savings_pct = (savings_needed / spending_data["monthly_average"] * 100) if spending_data["monthly_average"] > 0 else 0
            lines.append("")
            lines.append("## TARGET BUDGET REQUEST")
            lines.append(f"**User's Target Budget:** €{target_amount:.2f}")
            lines.append(f"**Current Monthly Average:** €{spending_data['monthly_average']:.2f}")
            if savings_needed > 0:
                lines.append(f"**Savings Required:** €{savings_needed:.2f} ({savings_pct:.1f}% reduction)")
            else:
                lines.append(f"**Budget Buffer:** €{abs(savings_needed):.2f} above current spending")

        lines.append("")
        lines.append("### Spending by Category:")

        # Sort categories by total
        sorted_cats = sorted(
            spending_data["by_category"].items(),
            key=lambda x: x[1]["total"],
            reverse=True,
        )
        for cat, data in sorted_cats:
            pct = (data["total"] / spending_data["total_spend"] * 100) if spending_data["total_spend"] > 0 else 0
            lines.append(f"- {cat}: €{data['total']:.2f} ({pct:.1f}%, {data['count']} items)")

        # Explicitly list all categories that MUST be included in allocations
        category_names = [cat for cat, _ in sorted_cats]
        lines.append("")
        lines.append("### REQUIRED CATEGORIES FOR ALLOCATION")
        lines.append("You MUST include a budget allocation for each of these categories:")
        lines.append(", ".join(category_names))
        lines.append(f"(Total: {len(category_names)} categories)")

        lines.append("")
        lines.append("### Weekly Spending Pattern:")
        for week, total in sorted(spending_data["by_week"].items())[-8:]:
            lines.append(f"- {week}: €{total:.2f}")

        lines.append("")
        lines.append("### Store Preferences:")
        sorted_stores = sorted(
            spending_data["by_store"].items(),
            key=lambda x: x[1]["total"],
            reverse=True,
        )[:5]
        for store, data in sorted_stores:
            lines.append(f"- {store}: €{data['total']:.2f} ({data['visits']} visits)")

        lines.append("")
        lines.append("### Day of Week Pattern:")
        for day, total in spending_data["by_day_of_week"].items():
            lines.append(f"- {day}: €{total:.2f}")

        return "\n".join(lines)

    def _build_checkin_prompt(self, progress_data: dict) -> str:
        """Build prompt for weekly check-in."""
        budget = progress_data["budget"]
        expected_spend = budget["monthly_amount"] * progress_data["days_elapsed"] / progress_data["days_in_month"]
        variance = progress_data["current_spend"] - expected_spend

        lines = [
            "## Current Budget Status",
            "",
            f"**Monthly Budget:** €{budget['monthly_amount']:.2f}",
            f"**Spent So Far:** €{progress_data['current_spend']:.2f} ({progress_data['current_spend']/budget['monthly_amount']*100:.1f}%)",
            f"**Days Elapsed:** {progress_data['days_elapsed']} of {progress_data['days_in_month']}",
            f"**Days Remaining:** {progress_data['days_remaining']}",
            "",
            "### Expected vs Actual",
            f"- Expected spend by now: €{expected_spend:.2f}",
            f"- Actual spend: €{progress_data['current_spend']:.2f}",
            f"- Variance: {'over' if variance > 0 else 'under'} by €{abs(variance):.2f}",
            "",
            "### Last 7 Days",
            f"- Total spent: €{progress_data['recent_spend']:.2f}",
        ]

        if progress_data["recent_transactions"]:
            lines.append("- Recent purchases:")
            for t in progress_data["recent_transactions"][:10]:
                lines.append(f"  - {t.item_name} (€{t.item_price:.2f}) at {t.store_name}")

        lines.append("")
        lines.append("### Category Progress")
        for cat, spent in sorted(
            progress_data["spend_by_category"].items(),
            key=lambda x: x[1],
            reverse=True,
        ):
            lines.append(f"- {cat}: €{spent:.2f}")

        lines.append("")
        lines.append("### Comparison to Last Month")
        if progress_data["last_month_same_period"] > 0:
            change = ((progress_data["current_spend"] - progress_data["last_month_same_period"]) / progress_data["last_month_same_period"] * 100)
            lines.append(f"- Same period last month: €{progress_data['last_month_same_period']:.2f}")
            lines.append(f"- This month: €{progress_data['current_spend']:.2f}")
            lines.append(f"- Change: {'+' if change > 0 else ''}{change:.1f}%")
        else:
            lines.append("- No data from last month for comparison")

        return "\n".join(lines)

    def _build_receipt_prompt(self, receipt_context: dict) -> str:
        """Build prompt for receipt analysis."""
        lines = [
            "## Receipt Just Scanned",
            "",
            f"**Store:** {receipt_context['store_name']}",
            f"**Total:** €{receipt_context['receipt_total']:.2f}",
            f"**Items:** {len(receipt_context['items'])}",
            "",
            "### Items Breakdown:",
        ]

        for item in receipt_context["items"]:
            lines.append(f"- {item.item_name}: €{item.item_price:.2f} ({item.category.value})")

        lines.append("")
        lines.append("## Budget Context")
        lines.append(f"**Monthly Budget:** €{receipt_context['budget_amount']:.2f}")
        lines.append(f"**Before this receipt:** €{receipt_context['spend_before']:.2f}")
        lines.append(f"**After this receipt:** €{receipt_context['spend_after']:.2f}")
        lines.append(f"**Remaining budget:** €{receipt_context['budget_remaining_after']:.2f}")
        lines.append(f"**Days remaining:** {receipt_context['days_remaining']}")

        return "\n".join(lines)

    def _build_monthly_report_prompt(self, monthly_data: dict) -> str:
        """Build prompt for monthly report."""
        lines = [
            f"## Month: {monthly_data['month']}",
            "",
            "### Budget Performance",
            f"- Budget: €{monthly_data['budget_amount']:.2f}",
            f"- Actual Spend: €{monthly_data['total_spent']:.2f}",
        ]

        if monthly_data["budget_amount"] > 0:
            diff = monthly_data["budget_amount"] - monthly_data["total_spent"]
            lines.append(f"- Result: {'Under' if diff > 0 else 'Over'} budget by €{abs(diff):.2f}")

        lines.append("")
        lines.append("### Category Breakdown")
        for cat, data in sorted(
            monthly_data["by_category"].items(),
            key=lambda x: x[1]["total"],
            reverse=True,
        ):
            pct = (data["total"] / monthly_data["total_spent"] * 100) if monthly_data["total_spent"] > 0 else 0
            lines.append(f"- {cat}: €{data['total']:.2f} ({pct:.1f}%, {data['count']} items)")

        lines.append("")
        lines.append("### Shopping Behavior")
        lines.append(f"- Total receipts: {monthly_data['receipt_count']}")
        if monthly_data["receipt_count"] > 0:
            avg = monthly_data["total_spent"] / monthly_data["receipt_count"]
            lines.append(f"- Average per trip: €{avg:.2f}")

        lines.append("")
        lines.append("### Store Distribution")
        for store, total in sorted(
            monthly_data["by_store"].items(),
            key=lambda x: x[1],
            reverse=True,
        )[:5]:
            lines.append(f"- {store}: €{total:.2f}")

        lines.append("")
        lines.append("### Month-over-Month Comparison")
        for prev in monthly_data["previous_months"]:
            lines.append(f"- {prev['month']}: €{prev['total']:.2f}")

        lines.append("")
        lines.append("### Top Items Purchased")
        for item, count in monthly_data["top_items"][:5]:
            lines.append(f"- {item}: {count}x")

        return "\n".join(lines)

    # =========================================================================
    # Response Parsing Helpers
    # =========================================================================

    def _call_gemini(self, user_prompt: str, system_prompt: str) -> str:
        """Call Gemini API and return the response text."""
        try:
            response = self.client.models.generate_content(
                model=self.MODEL,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=user_prompt)],
                    )
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=self.MAX_TOKENS,
                    temperature=0.7,
                ),
            )
            return response.text

        except Exception as e:
            logger.exception(f"Gemini API error: {e}")
            raise GeminiAPIError(
                f"Gemini API error: {str(e)}",
                details={"error_type": "api_error"},
            )

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from the response text."""
        # Try to find JSON in the response
        # First, try to parse the entire response
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Look for JSON block in markdown code fence
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try to find JSON object in the text
        brace_match = re.search(r"\{[\s\S]*\}", text)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        raise GeminiAPIError(
            "Failed to parse AI response as JSON",
            details={"error_type": "parse_error", "response_preview": text[:500]},
        )

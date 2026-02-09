from fastapi import APIRouter

# Import v2-specific endpoints (using Gemini)
from app.api.v2 import chat, receipts, periods, budgets, expense_splits, wallet_pass, categories, promos

# Reuse v1 endpoints that don't interact with LLMs
from app.api.v1 import health, transactions, analytics, rate_limit, profile

api_router = APIRouter()

# Health check
api_router.include_router(health.router, tags=["v2 - health"])

# Receipts - V2 using Gemini for categorization
api_router.include_router(receipts.router, prefix="/receipts", tags=["v2 - receipts"])

# Transactions - reuse from v1 (no LLM interaction)
api_router.include_router(
    transactions.router, prefix="/transactions", tags=["v2 - transactions"]
)

# Analytics - reuse from v1 (no LLM interaction)
api_router.include_router(analytics.router, prefix="/analytics", tags=["v2 - analytics"])

# Periods - V2 lightweight endpoint for period metadata
api_router.include_router(periods.router, prefix="/analytics", tags=["v2 - analytics"])

# Chat - V2 using Gemini
api_router.include_router(chat.router, prefix="/chat", tags=["v2 - chat"])

# Rate limit - reuse from v1 (no LLM interaction)
api_router.include_router(rate_limit.router, prefix="/rate-limit", tags=["v2 - rate-limit"])

# Profile - reuse from v1 (no LLM interaction)
api_router.include_router(profile.router, prefix="/profile", tags=["v2 - profile"])

# Budgets - V2 specific endpoint for budget tracking
api_router.include_router(budgets.router, prefix="/budgets", tags=["v2 - budgets"])

# Expense Splits - Split expenses among friends
api_router.include_router(expense_splits.router, prefix="/expense-splits", tags=["v2 - expense-splits"])

# Wallet Pass - Apple Wallet pass creation
api_router.include_router(wallet_pass.router, tags=["v2 - wallet-pass"])

# Categories - category hierarchy and usage data
api_router.include_router(categories.router, prefix="/categories", tags=["v2 - categories"])

# Promos - personalized promo recommendations
api_router.include_router(promos.router, prefix="/promos", tags=["v2 - promos"])

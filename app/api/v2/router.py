from fastapi import APIRouter

# Import v2-specific endpoints (using Gemini)
from app.api.v2 import auth, chat, receipts, periods, budgets, wallet_pass, categories, promos, cashback, spin, referral, withdrawal, streak, lottery

# Reuse v1 endpoints that don't interact with LLMs
from app.api.v1 import health, transactions, analytics, profile

api_router = APIRouter()

# Authentication - itsme OIDC login
api_router.include_router(auth.router, prefix="/auth", tags=["v2 - auth"])

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

# Profile - reuse from v1 (no LLM interaction)
api_router.include_router(profile.router, prefix="/profile", tags=["v2 - profile"])

# Budgets - V2 specific endpoint for budget tracking
api_router.include_router(budgets.router, prefix="/budgets", tags=["v2 - budgets"])

# Wallet Pass - Apple Wallet pass creation
api_router.include_router(wallet_pass.router, tags=["v2 - wallet-pass"])

# Categories - category hierarchy and usage data
api_router.include_router(categories.router, prefix="/categories", tags=["v2 - categories"])

# Promos - personalized promo recommendations
api_router.include_router(promos.router, prefix="/promos", tags=["v2 - promos"])

# Cashback - progressive cashback wallet
api_router.include_router(cashback.router, prefix="/cashback", tags=["v2 - cashback"])

# Spin wheel - prize wheel with server-side outcome determination
api_router.include_router(spin.router, prefix="/spin", tags=["v2 - spin"])

# Referral - dual-sided referral program
api_router.include_router(referral.router, prefix="/referral", tags=["v2 - referral"])

# Withdrawal - cash withdrawal to bank account
api_router.include_router(withdrawal.router, prefix="/withdrawal", tags=["v2 - withdrawal"])

# Streak - weekly streak rewards
api_router.include_router(streak.router, prefix="/streak", tags=["v2 - streak"])

# Lottery - monthly lottery drawing
api_router.include_router(lottery.router, prefix="/lottery", tags=["v2 - lottery"])

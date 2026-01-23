from fastapi import APIRouter

# Import v2-specific endpoints (using Gemini)
from app.api.v2 import chat, receipts

# Reuse v1 endpoints that don't interact with LLMs
from app.api.v1 import health, transactions, analytics, rate_limit, profile

api_router = APIRouter()

# Health check
api_router.include_router(health.router, tags=["health"])

# Receipts - V2 using Gemini for categorization
api_router.include_router(receipts.router, prefix="/receipts", tags=["receipts"])

# Transactions - reuse from v1 (no LLM interaction)
api_router.include_router(
    transactions.router, prefix="/transactions", tags=["transactions"]
)

# Analytics - reuse from v1 (no LLM interaction)
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])

# Chat - V2 using Gemini
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])

# Rate limit - reuse from v1 (no LLM interaction)
api_router.include_router(rate_limit.router, prefix="/rate-limit", tags=["rate-limit"])

# Profile - reuse from v1 (no LLM interaction)
api_router.include_router(profile.router, prefix="/profile", tags=["profile"])

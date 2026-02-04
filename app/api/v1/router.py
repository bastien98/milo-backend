from fastapi import APIRouter

from app.api.v1 import health, receipts, transactions, analytics, chat, rate_limit, profile

api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])
api_router.include_router(receipts.router, prefix="/receipts", tags=["receipts"])
api_router.include_router(
    transactions.router, prefix="/transactions", tags=["transactions"]
)
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(rate_limit.router, prefix="/rate-limit", tags=["rate-limit"])
api_router.include_router(profile.router, prefix="/profile", tags=["profile"])

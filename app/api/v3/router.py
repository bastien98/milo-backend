from fastapi import APIRouter

from app.api.v3 import receipts

api_router = APIRouter()

api_router.include_router(receipts.router, prefix="/receipts", tags=["receipts-v3"])

"""Quick test for the promo recommendation service (no auth needed)."""

import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to path
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv
load_dotenv(BACKEND_ROOT / ".env")

# Point at production Railway DB (must be set before importing app modules)
os.environ["DATABASE_URL"] = (
    "postgresql://postgres:hrGaUOZtYDDNPUDPmXlzpnVAReIgxlkx"
    "@switchback.proxy.rlwy.net:45896/railway"
)

from app.db.session import async_session_maker
# Import all models so SQLAlchemy can resolve relationships
from app.models import user, receipt, transaction, user_rate_limit, user_profile, budget, budget_ai_insight, budget_history, user_enriched_profile  # noqa
from app.services.promo_service import PromoService

USER_ID = os.environ.get("TEST_USER_ID", "c9b6bc31-d05a-4ab4-97fc-f40ff5fe6f67")


async def main():
    print(f"Testing promo recommendations for user: {USER_ID}\n")

    async with async_session_maker() as db:
        service = PromoService(db)
        result = await service.get_recommendations(USER_ID)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    # Quick summary
    print(f"\n{'='*50}")
    print(f"Weekly savings: €{result.get('weekly_savings', 0):.2f}")
    print(f"Deals found: {result.get('deal_count', 0)}")
    for i, pick in enumerate(result.get("top_picks", []), 1):
        print(f"  {i}. {pick.get('brand')} {pick.get('product_name')} — €{pick.get('promo_price', 0):.2f} (save €{pick.get('savings', 0):.2f}) at {pick.get('store')}")


if __name__ == "__main__":
    asyncio.run(main())

"""Manual dev tool: test promo candidate generation against production DB.

WARNING: This script connects directly to the production Railway database.
It is NOT a CI test — run it manually for local debugging only.
"""

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
from app.models import user, receipt, transaction, user_profile, budget, budget_ai_insight, budget_history, user_enriched_profile  # noqa
from scripts.promo_reports.promo_candidate_generation import PromoCandidateGenerationService

USER_ID = os.environ.get("TEST_USER_ID", "c9b6bc31-d05a-4ab4-97fc-f40ff5fe6f67")


async def main():
    print(f"Testing promo candidate generation for user: {USER_ID}\n")

    async with async_session_maker() as db:
        service = PromoCandidateGenerationService(db)
        result = await service.build_candidates(USER_ID)

    if result is None:
        print("No candidates generated (no interest items or no matches).")
        return

    print(json.dumps(result["candidates"][:5], indent=2, ensure_ascii=False))

    # Quick summary
    print(f"\n{'='*50}")
    print(f"Total candidates: {result['total_matches']}")
    print(f"Interest items: {result['interest_item_count']}")
    print(f"Closing nudge: {result['closing_nudge']}")
    for i, item in enumerate(result["candidates"][:3], 1):
        print(f"  {i}. {item.get('brand')} {item.get('product_name')} — €{item.get('promo_price', 0):.2f} (save €{item.get('savings', 0):.2f}) at {item.get('store_name')}")


if __name__ == "__main__":
    asyncio.run(main())

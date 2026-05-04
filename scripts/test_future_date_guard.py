"""One-shot E2E verification of Fix #6 (future-date guard) on prod.

Picks the most recent Delhaize receipt, builds the matcher's input from its
transactions, and invokes `check_receipt_for_brand_cashback` directly with
a `receipt_date` of tomorrow. Asserts:

- return value == 0
- no new earnings
- no new pending review rows
- balance unchanged

The session is rolled back at the end regardless, so even if the guard
silently fails and earnings get created, prod state is untouched.

Usage: DATABASE_URL=... python scripts/test_future_date_guard.py
"""
import asyncio
from datetime import date, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import get_settings
# Import every model module so SQLAlchemy can resolve relationship strings
# (e.g. User.enriched_profile -> "UserEnrichedProfile").
from app.models import (  # noqa: F401
    user, receipt, transaction, user_profile,
    budget, budget_history, user_enriched_profile,
    withdrawal, promo_item, promo_interaction_event,
    brand_cashback, brand_cashback_balance,
)
from app.models.brand_cashback import (
    BrandCashbackEarning, BrandCashbackPendingMatch,
)
from app.models.brand_cashback_balance import BrandCashbackBalance
from app.models.receipt import Receipt
from app.models.transaction import Transaction
from app.services.brand_cashback_service import (
    BrandCashbackService, ReceiptLineItemForMatching,
)


USER_ID = "18d8d4f0-5156-49f6-b53d-0aa737f7f9db"


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        # Pick the latest Delhaize receipt with multiple line items.
        latest = await db.execute(
            select(Receipt)
            .where(Receipt.store_name == "delhaize", Receipt.user_id == USER_ID)
            .order_by(Receipt.created_at.desc())
            .limit(1)
        )
        receipt = latest.scalar_one()

        txns = await db.execute(
            select(Transaction).where(Transaction.receipt_id == receipt.id)
        )
        receipt_items = [
            ReceiptLineItemForMatching(text=t.item_name, codes=tuple(t.dp_article_codes or []))
            for t in txns.scalars().all()
        ]
        print(f"Target receipt: {receipt.id}  store={receipt.store_name}  "
              f"actual_date={receipt.receipt_date}  items={len(receipt_items)}")

        async def state_snapshot() -> tuple[int, int, int]:
            earnings = await db.execute(select(func.count(BrandCashbackEarning.id)))
            pending = await db.execute(
                select(func.count(BrandCashbackPendingMatch.id))
                .where(BrandCashbackPendingMatch.status == "pending")
            )
            balance = await db.execute(
                select(BrandCashbackBalance.balance_cents).where(BrandCashbackBalance.user_id == USER_ID)
            )
            return (
                earnings.scalar() or 0,
                pending.scalar() or 0,
                balance.scalar() or 0,
            )

        pre = await state_snapshot()
        print(f"PRE — earnings={pre[0]}  pending={pre[1]}  balance_cents={pre[2]}")

        # Invoke matcher with FUTURE receipt date.
        future = date.today() + timedelta(days=1)
        print(f"\nInvoking matcher with receipt_date={future} (tomorrow)...")
        svc = BrandCashbackService(db)
        n = await svc.check_receipt_for_brand_cashback(
            receipt_id=receipt.id,
            user_id=USER_ID,
            receipt_line_items=receipt_items,
            store_name=receipt.store_name,
            receipt_date=future,
        )
        print(f"matcher returned: {n}")

        post = await state_snapshot()
        print(f"POST — earnings={post[0]}  pending={post[1]}  balance_cents={post[2]}")

        # Rollback regardless — defensive, so prod state is never touched
        # even if a write somehow leaked.
        await db.rollback()

        # Assertions
        assert n == 0, f"Expected 0 earnings, got {n}"
        assert post[0] == pre[0], f"Earnings count changed: {pre[0]} → {post[0]}"
        assert post[1] == pre[1], f"Pending count changed: {pre[1]} → {post[1]}"
        assert post[2] == pre[2], f"Balance changed: {pre[2]} → {post[2]}"

        print("\n✓ Future-date guard fired. All counters unchanged. Test passed.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

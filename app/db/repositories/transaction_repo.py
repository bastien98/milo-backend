from datetime import date
from typing import Optional, List

from sqlalchemy import select, func, and_, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.core.categories import get_internal_name


class TransactionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, transaction_id: str) -> Optional[Transaction]:
        """Get transaction by ID."""
        result = await self.db.execute(
            select(Transaction).where(Transaction.id == transaction_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_and_user(
        self, transaction_id: str, user_id: str
    ) -> Optional[Transaction]:
        """Get transaction by ID and user ID."""
        result = await self.db.execute(
            select(Transaction).where(
                Transaction.id == transaction_id,
                Transaction.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_user(
        self,
        user_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        store_name: Optional[str] = None,
        category: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[List[Transaction], int]:
        """Get transactions for a user with filters and pagination."""
        # Build filter conditions
        conditions = [Transaction.user_id == user_id]

        if start_date:
            conditions.append(Transaction.date >= start_date)
        if end_date:
            conditions.append(Transaction.date <= end_date)
        if store_name:
            conditions.append(Transaction.store_name == store_name)
        if category:
            # Resolve display name or variant to the internal name stored in the DB
            internal = get_internal_name(category)
            if internal:
                conditions.append(Transaction.category == internal)
            else:
                # Fallback: exact match for unknown categories
                conditions.append(Transaction.category == category)

        # Get total count
        count_result = await self.db.execute(
            select(func.count(Transaction.id)).where(and_(*conditions))
        )
        total = count_result.scalar() or 0

        # Get paginated results
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(Transaction)
            .where(and_(*conditions))
            .order_by(Transaction.date.desc(), Transaction.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        transactions = list(result.scalars().all())

        return transactions, total

    async def create(
        self,
        user_id: str,
        store_name: str,
        item_name: str,
        item_price: float,
        category: str,
        date: date,
        receipt_id: Optional[str] = None,
        quantity: int = 1,
        unit_price: Optional[float] = None,
        # New fields for semantic search
        normalized_name: Optional[str] = None,
        normalized_brand: Optional[str] = None,
        is_premium: bool = False,
        is_discount: bool = False,
        is_deposit: bool = False,
        is_deposit_refund: bool = False,
        granular_category: Optional[str] = None,
        # Unit measure fields
        unit_of_measure: Optional[str] = None,
        weight_or_volume: Optional[float] = None,
        price_per_unit_measure: Optional[float] = None,
        # Data Platform fields (dp_)
        dp_expanded_description: Optional[str] = None,
        dp_pack_quantity: Optional[int] = None,
        dp_pack_size: Optional[float] = None,
        dp_pack_unit: Optional[str] = None,
        dp_product_variant: Optional[str] = None,
        dp_article_code: Optional[str] = None,
        dp_is_bio: bool = False,
    ) -> Transaction:
        """Create a new transaction."""
        transaction = Transaction(
            user_id=user_id,
            receipt_id=receipt_id,
            store_name=store_name,
            item_name=item_name,
            item_price=item_price,
            quantity=quantity,
            unit_price=unit_price,
            category=category,
            date=date,
            # New fields
            normalized_name=normalized_name,
            normalized_brand=normalized_brand,
            is_premium=is_premium,
            is_discount=is_discount,
            is_deposit=is_deposit,
            is_deposit_refund=is_deposit_refund,
            granular_category=granular_category,
            # Unit measure fields
            unit_of_measure=unit_of_measure,
            weight_or_volume=weight_or_volume,
            price_per_unit_measure=price_per_unit_measure,
            # Data Platform fields
            dp_expanded_description=dp_expanded_description,
            dp_pack_quantity=dp_pack_quantity,
            dp_pack_size=dp_pack_size,
            dp_pack_unit=dp_pack_unit,
            dp_product_variant=dp_product_variant,
            dp_article_code=dp_article_code,
            dp_is_bio=dp_is_bio,
        )
        self.db.add(transaction)
        await self.db.flush()
        await self.db.refresh(transaction)
        return transaction

    async def create_batch(self, transactions: list[Transaction]) -> list[Transaction]:
        """Create multiple transactions with a single flush (much faster than N individual creates)."""
        for txn in transactions:
            self.db.add(txn)
        await self.db.flush()
        return transactions

    async def update(
        self,
        transaction_id: str,
        store_name: Optional[str] = None,
        item_name: Optional[str] = None,
        item_price: Optional[float] = None,
        quantity: Optional[int] = None,
        unit_price: Optional[float] = None,
        category: Optional[str] = None,
        date: Optional[date] = None,
    ) -> Optional[Transaction]:
        """Update a transaction."""
        transaction = await self.get_by_id(transaction_id)
        if not transaction:
            return None

        if store_name is not None:
            transaction.store_name = store_name
        if item_name is not None:
            transaction.item_name = item_name
        if item_price is not None:
            transaction.item_price = item_price
        if quantity is not None:
            transaction.quantity = quantity
        if unit_price is not None:
            transaction.unit_price = unit_price
        if category is not None:
            transaction.category = category
        if date is not None:
            transaction.date = date

        await self.db.flush()
        await self.db.refresh(transaction)
        return transaction

    async def delete(self, transaction_id: str) -> bool:
        """Delete a transaction."""
        transaction = await self.get_by_id(transaction_id)
        if not transaction:
            return False

        await self.db.delete(transaction)
        await self.db.flush()
        return True

    async def get_by_receipt(self, receipt_id: str) -> List[Transaction]:
        """Get all transactions for a receipt."""
        result = await self.db.execute(
            select(Transaction)
            .where(Transaction.receipt_id == receipt_id)
            .order_by(Transaction.created_at)
        )
        return list(result.scalars().all())

    async def delete_by_store_and_date_range(
        self,
        user_id: str,
        store_name: str,
        start_date: date,
        end_date: date,
    ) -> int:
        """Delete transactions for a user by store name and date range.

        Returns the number of deleted transactions.
        """
        # First count matching transactions
        count_result = await self.db.execute(
            select(func.count(Transaction.id)).where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.store_name == store_name,
                    Transaction.date >= start_date,
                    Transaction.date <= end_date,
                )
            )
        )
        count = count_result.scalar() or 0

        if count > 0:
            # Delete matching transactions
            await self.db.execute(
                delete(Transaction).where(
                    and_(
                        Transaction.user_id == user_id,
                        Transaction.store_name == store_name,
                        Transaction.date >= start_date,
                        Transaction.date <= end_date,
                    )
                )
            )
            await self.db.flush()

        return count

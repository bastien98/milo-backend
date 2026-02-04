from datetime import date
from typing import Optional, List, Tuple

from sqlalchemy import select, and_, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_transaction import BankTransaction, BankTransactionStatus
from app.models.bank_account import BankAccount
from app.models.bank_connection import BankConnection


class BankTransactionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, transaction_id: str) -> Optional[BankTransaction]:
        """Get transaction by ID."""
        result = await self.db.execute(
            select(BankTransaction).where(BankTransaction.id == transaction_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_and_user(
        self, transaction_id: str, user_id: str
    ) -> Optional[BankTransaction]:
        """Get transaction by ID, verifying user ownership."""
        result = await self.db.execute(
            select(BankTransaction)
            .join(BankAccount)
            .join(BankConnection)
            .where(
                BankTransaction.id == transaction_id,
                BankConnection.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_account(
        self,
        account_id: str,
        status: Optional[BankTransactionStatus] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[BankTransaction], int]:
        """Get transactions for an account with filters and pagination."""
        conditions = [BankTransaction.account_id == account_id]

        if status:
            conditions.append(BankTransaction.status == status)
        if start_date:
            conditions.append(BankTransaction.booking_date >= start_date)
        if end_date:
            conditions.append(BankTransaction.booking_date <= end_date)

        # Get total count
        count_result = await self.db.execute(
            select(func.count(BankTransaction.id)).where(and_(*conditions))
        )
        total = count_result.scalar() or 0

        # Get paginated results
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(BankTransaction)
            .where(and_(*conditions))
            .order_by(
                BankTransaction.booking_date.desc(),
                BankTransaction.created_at.desc(),
            )
            .offset(offset)
            .limit(page_size)
        )
        transactions = list(result.scalars().all())

        return transactions, total

    async def get_pending_by_user(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[BankTransaction], int]:
        """Get all pending transactions for a user across all accounts."""
        # Get total count
        count_result = await self.db.execute(
            select(func.count(BankTransaction.id))
            .select_from(BankTransaction)
            .join(BankAccount)
            .join(BankConnection)
            .where(
                BankConnection.user_id == user_id,
                BankTransaction.status == BankTransactionStatus.PENDING,
            )
        )
        total = count_result.scalar() or 0

        # Get paginated results
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(BankTransaction)
            .join(BankAccount)
            .join(BankConnection)
            .where(
                BankConnection.user_id == user_id,
                BankTransaction.status == BankTransactionStatus.PENDING,
            )
            .order_by(BankTransaction.booking_date.desc())
            .offset(offset)
            .limit(page_size)
        )
        transactions = list(result.scalars().all())

        return transactions, total

    async def get_pending_count_by_user(self, user_id: str) -> int:
        """Get count of pending transactions for a user across all accounts."""
        count_result = await self.db.execute(
            select(func.count(BankTransaction.id))
            .select_from(BankTransaction)
            .join(BankAccount)
            .join(BankConnection)
            .where(
                BankConnection.user_id == user_id,
                BankTransaction.status == BankTransactionStatus.PENDING,
            )
        )
        return count_result.scalar() or 0

    async def exists(self, account_id: str, transaction_id: str) -> bool:
        """Check if a transaction already exists."""
        result = await self.db.execute(
            select(func.count(BankTransaction.id)).where(
                BankTransaction.account_id == account_id,
                BankTransaction.transaction_id == transaction_id,
            )
        )
        return (result.scalar() or 0) > 0

    async def get_by_account_and_transaction_id(
        self, account_id: str, transaction_id: str
    ) -> Optional[BankTransaction]:
        """Get a transaction by account and transaction ID."""
        result = await self.db.execute(
            select(BankTransaction).where(
                BankTransaction.account_id == account_id,
                BankTransaction.transaction_id == transaction_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        account_id: str,
        transaction_id: str,
        amount: float,
        booking_date: date,
        currency: str = "EUR",
        creditor_name: Optional[str] = None,
        creditor_iban: Optional[str] = None,
        debtor_name: Optional[str] = None,
        debtor_iban: Optional[str] = None,
        value_date: Optional[date] = None,
        description: Optional[str] = None,
        remittance_info: Optional[str] = None,
        entry_reference: Optional[str] = None,
        raw_response: Optional[dict] = None,
        suggested_category: Optional[str] = None,
        category_confidence: Optional[float] = None,
    ) -> BankTransaction:
        """Create a new bank transaction."""
        transaction = BankTransaction(
            account_id=account_id,
            transaction_id=transaction_id,
            amount=amount,
            currency=currency,
            creditor_name=creditor_name,
            creditor_iban=creditor_iban,
            debtor_name=debtor_name,
            debtor_iban=debtor_iban,
            booking_date=booking_date,
            value_date=value_date,
            description=description,
            remittance_info=remittance_info,
            entry_reference=entry_reference,
            status=BankTransactionStatus.PENDING,
            raw_response=raw_response,
            suggested_category=suggested_category,
            category_confidence=category_confidence,
        )
        self.db.add(transaction)
        await self.db.flush()
        await self.db.refresh(transaction)
        return transaction

    async def update_status(
        self,
        transaction: BankTransaction,
        status: BankTransactionStatus,
        imported_transaction_id: Optional[str] = None,
    ) -> BankTransaction:
        """Update transaction status."""
        transaction.status = status
        if imported_transaction_id:
            transaction.imported_transaction_id = imported_transaction_id

        await self.db.flush()
        await self.db.refresh(transaction)
        return transaction

    async def update_category_suggestion(
        self,
        transaction: BankTransaction,
        suggested_category: str,
        category_confidence: float,
    ) -> BankTransaction:
        """Update the AI-suggested category for a transaction."""
        transaction.suggested_category = suggested_category
        transaction.category_confidence = category_confidence

        await self.db.flush()
        await self.db.refresh(transaction)
        return transaction

    async def bulk_update_status(
        self, transaction_ids: List[str], status: BankTransactionStatus
    ) -> int:
        """Bulk update transaction statuses. Returns count updated."""
        result = await self.db.execute(
            update(BankTransaction)
            .where(BankTransaction.id.in_(transaction_ids))
            .values(status=status)
        )
        await self.db.flush()
        return result.rowcount

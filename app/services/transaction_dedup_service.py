from datetime import date, timedelta
from typing import Optional, List

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_transaction import BankTransaction, BankTransactionStatus
from app.models.bank_account import BankAccount
from app.models.bank_connection import BankConnection
from app.models.receipt import Receipt


class TransactionDedupService:
    """Detects and handles duplicate transactions between receipts and bank imports.

    When a user scans a receipt AND the same payment appears via bank import,
    the receipt is kept (because it has line-item detail) and the bank
    transaction is marked as receipt_matched.
    """

    # Matching thresholds
    DATE_TOLERANCE_DAYS = 2
    AMOUNT_TOLERANCE_PCT = 0.10  # 10%

    def __init__(self, db: AsyncSession):
        self.db = db

    async def find_matching_bank_transactions(
        self,
        user_id: str,
        store_name: str,
        receipt_date: date,
        total_amount: float,
    ) -> List[BankTransaction]:
        """Find bank transactions that likely match a scanned receipt.

        Matches on date (within 2 days), amount (within 10%), and
        store/creditor name similarity. Only considers PENDING bank
        transactions (not already imported, ignored, or matched).
        """
        # Date range
        date_start = receipt_date - timedelta(days=self.DATE_TOLERANCE_DAYS)
        date_end = receipt_date + timedelta(days=self.DATE_TOLERANCE_DAYS)

        # Amount range (within 10%) - use absolute value for comparison
        abs_amount = abs(total_amount)
        amount_low = abs_amount * (1 - self.AMOUNT_TOLERANCE_PCT)
        amount_high = abs_amount * (1 + self.AMOUNT_TOLERANCE_PCT)

        # Query bank transactions via BankAccount -> BankConnection for user filtering
        # Bank transactions store amounts as negative for expenses, so we compare
        # against both the positive and negative range
        result = await self.db.execute(
            select(BankTransaction)
            .join(BankAccount, BankTransaction.account_id == BankAccount.id)
            .join(BankConnection, BankAccount.connection_id == BankConnection.id)
            .where(
                and_(
                    BankConnection.user_id == user_id,
                    BankTransaction.booking_date >= date_start,
                    BankTransaction.booking_date <= date_end,
                    # Match absolute amount: bank txns can be negative (expenses)
                    # so we check if abs(amount) is within tolerance
                    BankTransaction.amount <= -amount_low,  # negative expenses
                    BankTransaction.amount >= -amount_high,
                    BankTransaction.status == BankTransactionStatus.PENDING,
                )
            )
        )
        candidates = list(result.scalars().all())

        # Also check positive amounts (in case some are stored positive)
        result_positive = await self.db.execute(
            select(BankTransaction)
            .join(BankAccount, BankTransaction.account_id == BankAccount.id)
            .join(BankConnection, BankAccount.connection_id == BankConnection.id)
            .where(
                and_(
                    BankConnection.user_id == user_id,
                    BankTransaction.booking_date >= date_start,
                    BankTransaction.booking_date <= date_end,
                    BankTransaction.amount >= amount_low,
                    BankTransaction.amount <= amount_high,
                    BankTransaction.status == BankTransactionStatus.PENDING,
                )
            )
        )
        candidates.extend(result_positive.scalars().all())

        # Deduplicate by id (in case both queries return the same transaction)
        seen_ids = set()
        unique_candidates = []
        for bt in candidates:
            if bt.id not in seen_ids:
                seen_ids.add(bt.id)
                unique_candidates.append(bt)

        # Further filter by store name similarity
        matches = []
        store_lower = store_name.lower().strip() if store_name else ""
        for bt in unique_candidates:
            creditor = (bt.creditor_name or "").lower().strip()
            # Simple substring matching - if store name appears in creditor or vice versa
            if store_lower and creditor:
                if store_lower in creditor or creditor in store_lower:
                    matches.append(bt)
                    continue
                # Check first word match (e.g., "colruyt" in "COLRUYT LAAGSTE PRIJS")
                store_words = store_lower.split()
                creditor_words = creditor.split()
                if store_words and creditor_words:
                    if store_words[0] in creditor_words or creditor_words[0] in store_words:
                        matches.append(bt)

        return matches

    async def find_matching_receipt(
        self,
        user_id: str,
        creditor_name: str,
        booking_date: date,
        amount: float,
    ) -> Optional[Receipt]:
        """Find a receipt that matches a bank transaction.

        Used during bank sync to check if an incoming bank transaction
        already has a corresponding scanned receipt.
        """
        date_start = booking_date - timedelta(days=self.DATE_TOLERANCE_DAYS)
        date_end = booking_date + timedelta(days=self.DATE_TOLERANCE_DAYS)

        abs_amount = abs(amount)
        amount_low = abs_amount * (1 - self.AMOUNT_TOLERANCE_PCT)
        amount_high = abs_amount * (1 + self.AMOUNT_TOLERANCE_PCT)

        result = await self.db.execute(
            select(Receipt)
            .where(
                and_(
                    Receipt.user_id == user_id,
                    Receipt.receipt_date >= date_start,
                    Receipt.receipt_date <= date_end,
                    Receipt.total_amount >= amount_low,
                    Receipt.total_amount <= amount_high,
                )
            )
        )
        candidates = list(result.scalars().all())

        creditor_lower = creditor_name.lower().strip() if creditor_name else ""
        for receipt in candidates:
            store_lower = (receipt.store_name or "").lower().strip()
            if store_lower and creditor_lower:
                if store_lower in creditor_lower or creditor_lower in store_lower:
                    return receipt
                store_words = store_lower.split()
                creditor_words = creditor_lower.split()
                if store_words and creditor_words:
                    if store_words[0] in creditor_words or creditor_words[0] in store_words:
                        return receipt

        return None

    async def mark_bank_transaction_matched(
        self,
        bank_transaction: BankTransaction,
        receipt_id: str,
    ):
        """Mark a bank transaction as matched to a receipt."""
        bank_transaction.status = BankTransactionStatus.RECEIPT_MATCHED
        bank_transaction.matched_receipt_id = receipt_id
        await self.db.flush()

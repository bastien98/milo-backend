from datetime import date, datetime, time
from typing import Optional, List

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.receipt import Receipt
from app.models.enums import ReceiptStatus, ReceiptSource


class ReceiptRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, receipt_id: str) -> Optional[Receipt]:
        """Get receipt by ID."""
        result = await self.db.execute(
            select(Receipt).where(Receipt.id == receipt_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_and_user(
        self, receipt_id: str, user_id: str
    ) -> Optional[Receipt]:
        """Get receipt by ID and user ID."""
        result = await self.db.execute(
            select(Receipt).where(
                Receipt.id == receipt_id,
                Receipt.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_user(
        self,
        user_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[Receipt], int]:
        """Get receipts for a user with optional date filtering and pagination.

        Filters by receipt_date (the date on the receipt), not created_at.
        """
        # Build filter conditions
        conditions = [Receipt.user_id == user_id]

        if start_date:
            conditions.append(Receipt.receipt_date >= start_date)
        if end_date:
            conditions.append(Receipt.receipt_date <= end_date)

        # Get total count with filters applied
        count_result = await self.db.execute(
            select(func.count(Receipt.id)).where(and_(*conditions))
        )
        total = count_result.scalar() or 0

        # Get paginated results with filters applied
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(Receipt)
            .where(and_(*conditions))
            .order_by(Receipt.receipt_date.desc(), Receipt.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        receipts = list(result.scalars().all())

        return receipts, total

    async def find_by_content_hash(self, content_hash: str) -> Optional[Receipt]:
        """Find any non-failed receipt with the given content hash (global, cross-user).

        Excludes FAILED receipts so users can retry failed uploads.
        """
        result = await self.db.execute(
            select(Receipt).where(
                Receipt.content_hash == content_hash,
                Receipt.status != ReceiptStatus.FAILED,
            ).limit(1)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        user_id: str,
        filename: str,
        file_type: str,
        file_size: int,
        status: ReceiptStatus = ReceiptStatus.PENDING,
        storage_key: Optional[str] = None,
        content_hash: Optional[str] = None,
    ) -> Receipt:
        """Create a new receipt."""
        receipt = Receipt(
            user_id=user_id,
            original_filename=filename,
            file_type=file_type,
            file_size_bytes=file_size,
            status=status,
            source=ReceiptSource.RECEIPT_UPLOAD,
            storage_key=storage_key,
            content_hash=content_hash,
        )
        self.db.add(receipt)
        await self.db.flush()
        await self.db.refresh(receipt)
        return receipt

    async def update(
        self,
        receipt_id: str,
        status: Optional[ReceiptStatus] = None,
        store_name: Optional[str] = None,
        receipt_date: Optional[date] = None,
        total_amount: Optional[float] = None,
        error_message: Optional[str] = None,
        error_code: Optional[str] = None,
        processed_at: Optional[datetime] = None,
        receipt_time: Optional[time] = None,
        payment_method: Optional[str] = None,
        store_branch: Optional[str] = None,
        storage_key: Optional[str] = None,
        content_hash: Optional[str] = None,
    ) -> Optional[Receipt]:
        """Update a receipt."""
        receipt = await self.get_by_id(receipt_id)
        if not receipt:
            return None

        if status is not None:
            receipt.status = status
        if store_name is not None:
            receipt.store_name = store_name
        if receipt_date is not None:
            receipt.receipt_date = receipt_date
        if total_amount is not None:
            receipt.total_amount = total_amount
        if error_message is not None:
            receipt.error_message = error_message
        if error_code is not None:
            receipt.error_code = error_code
        if processed_at is not None:
            receipt.processed_at = processed_at
        if receipt_time is not None:
            receipt.receipt_time = receipt_time
        if payment_method is not None:
            receipt.payment_method = payment_method
        if store_branch is not None:
            receipt.store_branch = store_branch
        if storage_key is not None:
            receipt.storage_key = storage_key
        if content_hash is not None:
            receipt.content_hash = content_hash

        await self.db.flush()
        await self.db.refresh(receipt)
        return receipt

    async def get_by_user_with_transactions(
        self,
        user_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        store_name: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[Receipt], int]:
        """Get receipts with eagerly loaded transactions, paginated at DB level.

        Much faster than loading all transactions and grouping in Python.
        """
        conditions = [
            Receipt.user_id == user_id,
            Receipt.status == ReceiptStatus.COMPLETED,
        ]

        if start_date:
            conditions.append(Receipt.receipt_date >= start_date)
        if end_date:
            conditions.append(Receipt.receipt_date <= end_date)
        if store_name:
            conditions.append(Receipt.store_name == store_name)

        # Count total matching receipts
        count_result = await self.db.execute(
            select(func.count(Receipt.id)).where(and_(*conditions))
        )
        total = count_result.scalar() or 0

        # Fetch paginated receipts with transactions eagerly loaded
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(Receipt)
            .options(selectinload(Receipt.transactions))
            .where(and_(*conditions))
            .order_by(Receipt.receipt_date.desc(), Receipt.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        receipts = list(result.scalars().unique().all())

        return receipts, total

    async def delete(self, receipt_id: str) -> bool:
        """Delete a receipt and its transactions."""
        receipt = await self.get_by_id(receipt_id)
        if not receipt:
            return False

        await self.db.delete(receipt)
        await self.db.flush()
        return True

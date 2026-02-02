from datetime import date, datetime
from typing import Optional, List

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

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

    async def create(
        self,
        user_id: str,
        filename: str,
        file_type: str,
        file_size: int,
        status: ReceiptStatus = ReceiptStatus.PENDING,
    ) -> Receipt:
        """Create a new receipt."""
        receipt = Receipt(
            user_id=user_id,
            original_filename=filename,
            file_type=file_type,
            file_size_bytes=file_size,
            status=status,
            source=ReceiptSource.RECEIPT_UPLOAD,
        )
        self.db.add(receipt)
        await self.db.flush()
        await self.db.refresh(receipt)
        return receipt

    async def create_from_bank_import(
        self,
        user_id: str,
        store_name: str,
        receipt_date: date,
        total_amount: float,
    ) -> Receipt:
        """Create a receipt from a bank transaction import."""
        receipt = Receipt(
            user_id=user_id,
            original_filename=None,
            file_type=None,
            file_size_bytes=None,
            status=ReceiptStatus.COMPLETED,
            source=ReceiptSource.BANK_IMPORT,
            store_name=store_name,
            receipt_date=receipt_date,
            total_amount=total_amount,
            processed_at=datetime.now(),
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
        processed_at: Optional[datetime] = None,
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
        if processed_at is not None:
            receipt.processed_at = processed_at

        await self.db.flush()
        await self.db.refresh(receipt)
        return receipt

    async def delete(self, receipt_id: str) -> bool:
        """Delete a receipt and its transactions."""
        receipt = await self.get_by_id(receipt_id)
        if not receipt:
            return False

        await self.db.delete(receipt)
        await self.db.flush()
        return True

from datetime import date, datetime
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.receipt import Receipt
from app.models.enums import ReceiptStatus


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
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[Receipt], int]:
        """Get receipts for a user with pagination."""
        # Get total count
        count_result = await self.db.execute(
            select(func.count(Receipt.id)).where(Receipt.user_id == user_id)
        )
        total = count_result.scalar() or 0

        # Get paginated results
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(Receipt)
            .where(Receipt.user_id == user_id)
            .order_by(Receipt.created_at.desc())
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

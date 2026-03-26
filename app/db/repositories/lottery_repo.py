import uuid
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lottery import LotteryDrawing, LotteryEntry


class LotteryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_drawing_by_month(self, month: str) -> Optional[LotteryDrawing]:
        result = await self.db.execute(
            select(LotteryDrawing).where(LotteryDrawing.month == month)
        )
        return result.scalar_one_or_none()

    async def get_or_create_drawing(self, month: str) -> LotteryDrawing:
        drawing = await self.get_drawing_by_month(month)
        if drawing is None:
            drawing = LotteryDrawing(
                id=str(uuid.uuid4()),
                month=month,
                status="pending",
            )
            self.db.add(drawing)
            await self.db.flush()
        return drawing

    async def update_drawing(self, drawing: LotteryDrawing, **kwargs) -> LotteryDrawing:
        for key, value in kwargs.items():
            setattr(drawing, key, value)
        await self.db.flush()
        await self.db.refresh(drawing)
        return drawing

    async def get_entries_for_drawing(self, drawing_id: str) -> list[LotteryEntry]:
        result = await self.db.execute(
            select(LotteryEntry)
            .where(LotteryEntry.drawing_id == drawing_id)
            .order_by(LotteryEntry.entry_number.nulls_last(), LotteryEntry.created_at)
        )
        return list(result.scalars().all())

    async def get_eligible_entries(self, drawing_id: str) -> list[LotteryEntry]:
        result = await self.db.execute(
            select(LotteryEntry)
            .where(
                LotteryEntry.drawing_id == drawing_id,
                LotteryEntry.is_eligible == True,
            )
            .order_by(LotteryEntry.entry_number)
        )
        return list(result.scalars().all())

    async def upsert_entry(
        self,
        drawing_id: str,
        user_id: str,
        instagram_handle: Optional[str] = None,
        display_name: Optional[str] = None,
        has_receipt_activity: bool = False,
        has_instagram_share: bool = False,
    ) -> LotteryEntry:
        result = await self.db.execute(
            select(LotteryEntry).where(
                LotteryEntry.drawing_id == drawing_id,
                LotteryEntry.user_id == user_id,
            )
        )
        entry = result.scalar_one_or_none()

        if entry:
            entry.instagram_handle = instagram_handle or entry.instagram_handle
            entry.display_name = display_name or entry.display_name
            entry.has_receipt_activity = has_receipt_activity
            entry.has_instagram_share = has_instagram_share
            entry.is_eligible = has_receipt_activity and has_instagram_share
        else:
            entry = LotteryEntry(
                id=str(uuid.uuid4()),
                drawing_id=drawing_id,
                user_id=user_id,
                instagram_handle=instagram_handle,
                display_name=display_name,
                has_receipt_activity=has_receipt_activity,
                has_instagram_share=has_instagram_share,
                is_eligible=has_receipt_activity and has_instagram_share,
            )
            self.db.add(entry)

        await self.db.flush()
        return entry

    async def toggle_share(self, drawing_id: str, user_id: str, shared: bool) -> None:
        await self.db.execute(
            update(LotteryEntry)
            .where(
                LotteryEntry.drawing_id == drawing_id,
                LotteryEntry.user_id == user_id,
            )
            .values(
                has_instagram_share=shared,
                is_eligible=LotteryEntry.has_receipt_activity & shared,
            )
        )
        await self.db.flush()

    async def get_entry_by_number(self, drawing_id: str, entry_number: int) -> Optional[LotteryEntry]:
        result = await self.db.execute(
            select(LotteryEntry).where(
                LotteryEntry.drawing_id == drawing_id,
                LotteryEntry.entry_number == entry_number,
            )
        )
        return result.scalar_one_or_none()

    async def declare_share(self, drawing_id: str, user_id: str) -> None:
        result = await self.db.execute(
            select(LotteryEntry).where(
                LotteryEntry.drawing_id == drawing_id,
                LotteryEntry.user_id == user_id,
            )
        )
        entry = result.scalar_one_or_none()
        if entry is None:
            entry = LotteryEntry(
                id=str(uuid.uuid4()),
                drawing_id=drawing_id,
                user_id=user_id,
                proof_status="pending_review",
            )
            self.db.add(entry)
        else:
            entry.proof_status = "pending_review"
        await self.db.flush()

    async def approve_proof(self, entry_id: str, approved: bool) -> None:
        status = "approved" if approved else "rejected"
        values: dict = {"proof_status": status}
        if approved:
            values["has_instagram_share"] = True
            values["is_eligible"] = True
        else:
            values["has_instagram_share"] = False
            values["is_eligible"] = False
        await self.db.execute(
            update(LotteryEntry)
            .where(LotteryEntry.id == entry_id)
            .values(**values)
        )
        await self.db.flush()

    async def get_entry_by_id(self, entry_id: str) -> Optional[LotteryEntry]:
        result = await self.db.execute(
            select(LotteryEntry).where(LotteryEntry.id == entry_id)
        )
        return result.scalar_one_or_none()

    async def get_all_drawings(self) -> list[LotteryDrawing]:
        result = await self.db.execute(
            select(LotteryDrawing).order_by(LotteryDrawing.month.desc())
        )
        return list(result.scalars().all())

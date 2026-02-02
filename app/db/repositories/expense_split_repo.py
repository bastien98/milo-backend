from datetime import datetime
from typing import Optional, List

from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.expense_split import (
    ExpenseSplit,
    SplitParticipant,
    SplitAssignment,
    RecentFriend,
)


class ExpenseSplitRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # MARK: - ExpenseSplit CRUD

    async def get_by_id(self, split_id: str) -> Optional[ExpenseSplit]:
        """Get expense split by ID with all related data."""
        result = await self.db.execute(
            select(ExpenseSplit)
            .options(
                selectinload(ExpenseSplit.participants),
                selectinload(ExpenseSplit.assignments),
            )
            .where(ExpenseSplit.id == split_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_and_user(
        self, split_id: str, user_id: str
    ) -> Optional[ExpenseSplit]:
        """Get expense split by ID and user ID."""
        result = await self.db.execute(
            select(ExpenseSplit)
            .options(
                selectinload(ExpenseSplit.participants),
                selectinload(ExpenseSplit.assignments),
            )
            .where(
                ExpenseSplit.id == split_id,
                ExpenseSplit.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_receipt(
        self, receipt_id: str, user_id: str
    ) -> Optional[ExpenseSplit]:
        """Get expense split for a receipt."""
        result = await self.db.execute(
            select(ExpenseSplit)
            .options(
                selectinload(ExpenseSplit.participants),
                selectinload(ExpenseSplit.assignments),
            )
            .where(
                ExpenseSplit.receipt_id == receipt_id,
                ExpenseSplit.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_user(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> List[ExpenseSplit]:
        """Get all expense splits for a user."""
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(ExpenseSplit)
            .options(
                selectinload(ExpenseSplit.participants),
                selectinload(ExpenseSplit.assignments),
            )
            .where(ExpenseSplit.user_id == user_id)
            .order_by(ExpenseSplit.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        return list(result.scalars().all())

    async def create(
        self,
        user_id: str,
        receipt_id: str,
    ) -> ExpenseSplit:
        """Create a new expense split."""
        split = ExpenseSplit(
            user_id=user_id,
            receipt_id=receipt_id,
        )
        self.db.add(split)
        await self.db.flush()
        await self.db.refresh(split)
        return split

    async def delete(self, split_id: str) -> bool:
        """Delete an expense split and all related data."""
        split = await self.get_by_id(split_id)
        if not split:
            return False

        await self.db.delete(split)
        await self.db.flush()
        return True

    # MARK: - SplitParticipant CRUD

    async def add_participant(
        self,
        split_id: str,
        name: str,
        color: str,
        display_order: int = 0,
    ) -> SplitParticipant:
        """Add a participant to a split."""
        participant = SplitParticipant(
            split_id=split_id,
            name=name,
            color=color,
            display_order=display_order,
        )
        self.db.add(participant)
        await self.db.flush()
        await self.db.refresh(participant)
        return participant

    async def remove_participant(self, participant_id: str) -> bool:
        """Remove a participant from a split."""
        result = await self.db.execute(
            select(SplitParticipant).where(SplitParticipant.id == participant_id)
        )
        participant = result.scalar_one_or_none()
        if not participant:
            return False

        await self.db.delete(participant)
        await self.db.flush()
        return True

    async def clear_participants(self, split_id: str) -> None:
        """Remove all participants from a split."""
        await self.db.execute(
            delete(SplitParticipant).where(SplitParticipant.split_id == split_id)
        )
        await self.db.flush()

    # MARK: - SplitAssignment CRUD

    async def set_assignment(
        self,
        split_id: str,
        transaction_id: str,
        participant_ids: List[str],
    ) -> SplitAssignment:
        """Set or update the assignment for a transaction."""
        # Check if assignment exists
        result = await self.db.execute(
            select(SplitAssignment).where(
                SplitAssignment.split_id == split_id,
                SplitAssignment.transaction_id == transaction_id,
            )
        )
        assignment = result.scalar_one_or_none()

        if assignment:
            # Update existing
            assignment.participant_ids = participant_ids
            assignment.updated_at = datetime.utcnow()
        else:
            # Create new
            assignment = SplitAssignment(
                split_id=split_id,
                transaction_id=transaction_id,
                participant_ids=participant_ids,
            )
            self.db.add(assignment)

        await self.db.flush()
        await self.db.refresh(assignment)
        return assignment

    async def create_assignment(
        self,
        split_id: str,
        transaction_id: str,
        participant_ids: List[str],
    ) -> SplitAssignment:
        """Create a new assignment for a transaction (always creates, never updates)."""
        assignment = SplitAssignment(
            split_id=split_id,
            transaction_id=transaction_id,
            participant_ids=participant_ids,
        )
        self.db.add(assignment)
        await self.db.flush()
        await self.db.refresh(assignment)
        return assignment

    async def get_assignments_by_split(self, split_id: str) -> List[SplitAssignment]:
        """Get all assignments for a split."""
        result = await self.db.execute(
            select(SplitAssignment).where(SplitAssignment.split_id == split_id)
        )
        return list(result.scalars().all())

    async def clear_assignments(self, split_id: str) -> None:
        """Remove all assignments from a split."""
        await self.db.execute(
            delete(SplitAssignment).where(SplitAssignment.split_id == split_id)
        )
        await self.db.flush()

    # MARK: - RecentFriend CRUD

    async def get_recent_friends(
        self, user_id: str, limit: int = 10
    ) -> List[RecentFriend]:
        """Get recent friends for a user, sorted by last used."""
        result = await self.db.execute(
            select(RecentFriend)
            .where(RecentFriend.user_id == user_id)
            .order_by(RecentFriend.last_used_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def upsert_recent_friend(
        self,
        user_id: str,
        name: str,
        color: str,
    ) -> RecentFriend:
        """Add or update a recent friend."""
        # Check if friend exists
        result = await self.db.execute(
            select(RecentFriend).where(
                RecentFriend.user_id == user_id,
                RecentFriend.name == name,
            )
        )
        friend = result.scalar_one_or_none()

        if friend:
            # Update existing
            friend.color = color
            friend.last_used_at = datetime.utcnow()
            friend.use_count += 1
        else:
            # Create new
            friend = RecentFriend(
                user_id=user_id,
                name=name,
                color=color,
            )
            self.db.add(friend)

        await self.db.flush()
        await self.db.refresh(friend)
        return friend

    async def update_recent_friends_from_split(
        self, user_id: str, participants: List[SplitParticipant]
    ) -> None:
        """Update recent friends based on participants used in a split."""
        for participant in participants:
            await self.upsert_recent_friend(
                user_id=user_id,
                name=participant.name,
                color=participant.color,
            )

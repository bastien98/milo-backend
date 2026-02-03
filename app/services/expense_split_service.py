import logging
from typing import Optional, List, Dict

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.db.repositories.expense_split_repo import ExpenseSplitRepository
from app.db.repositories.transaction_repo import TransactionRepository
from app.db.repositories.receipt_repo import ReceiptRepository
from app.models.expense_split import ExpenseSplit, SplitParticipant
from app.schemas.expense_split import (
    ExpenseSplitCreate,
    ExpenseSplitResponse,
    SplitParticipantResponse,
    SplitAssignmentResponse,
    ParticipantTotal,
    SplitCalculationResponse,
    RecentFriendResponse,
    FRIEND_COLORS,
)
from app.core.exceptions import ResourceNotFoundError


class ExpenseSplitService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.split_repo = ExpenseSplitRepository(db)
        self.transaction_repo = TransactionRepository(db)
        self.receipt_repo = ReceiptRepository(db)

    async def create_split(
        self,
        user_id: str,
        data: ExpenseSplitCreate,
    ) -> ExpenseSplitResponse:
        """Create a new expense split for a receipt."""
        # Verify receipt exists and belongs to user
        receipt = await self.receipt_repo.get_by_id_and_user(
            data.receipt_id, user_id
        )
        if not receipt:
            raise ResourceNotFoundError(f"Receipt {data.receipt_id} not found")

        # Check if split already exists for this receipt
        existing = await self.split_repo.get_by_receipt(data.receipt_id, user_id)
        if existing:
            # Update existing split instead
            return await self.update_split(user_id, existing.id, data)

        # Create the split
        split = await self.split_repo.create(
            user_id=user_id,
            receipt_id=data.receipt_id,
        )

        # Add participants
        for i, participant_data in enumerate(data.participants):
            await self.split_repo.add_participant(
                split_id=split.id,
                name=participant_data.name,
                color=participant_data.color,
                display_order=i,
                custom_amount=participant_data.custom_amount,
            )

        # Flush to ensure participants are written to DB before querying
        await self.db.flush()

        # Refresh to get participants with eager loading
        split = await self.split_repo.get_by_id(split.id)

        # Create index-to-backend-UUID mapping
        # iOS sends participant indices (0, 1, 2, ...) instead of UUIDs
        sorted_participants = sorted(split.participants, key=lambda x: x.display_order)
        index_to_backend_id = {str(i): p.id for i, p in enumerate(sorted_participants)}

        # Add assignments
        for assignment_data in data.assignments:
            # Convert indices to backend participant UUIDs
            backend_participant_ids = []
            for participant_ref in assignment_data.participant_ids:
                if participant_ref in index_to_backend_id:
                    # It's an index - map to backend UUID
                    backend_participant_ids.append(index_to_backend_id[participant_ref])
                else:
                    # Fallback: might be a UUID already (for backwards compatibility)
                    backend_participant_ids.append(participant_ref)

            await self.split_repo.set_assignment(
                split_id=split.id,
                transaction_id=assignment_data.transaction_id,
                participant_ids=backend_participant_ids,
            )

        # Update recent friends
        await self.split_repo.update_recent_friends_from_split(
            user_id=user_id,
            participants=split.participants,
        )

        # Commit to persist all changes
        await self.db.commit()

        # Store split_id before expiring (accessing attributes after expire triggers lazy load)
        split_id = split.id

        # Expire the cached object to ensure fresh relationship data is loaded
        # (required because expire_on_commit=False in session config)
        self.db.expire(split)
        split = await self.split_repo.get_by_id(split_id)
        return self._to_response(split)

    async def update_split(
        self,
        user_id: str,
        split_id: str,
        data: ExpenseSplitCreate,
    ) -> ExpenseSplitResponse:
        """Update an existing expense split."""
        split = await self.split_repo.get_by_id_and_user(split_id, user_id)
        if not split:
            raise ResourceNotFoundError(f"Split {split_id} not found")

        # Clear existing participants and assignments
        await self.split_repo.clear_assignments(split_id)
        await self.split_repo.clear_participants(split_id)

        # Expire all cached objects to ensure we don't use stale data
        # This is critical because clear_assignments/clear_participants use bulk deletes
        # which don't update the session's identity map
        self.db.expire_all()

        # Add new participants
        for i, participant_data in enumerate(data.participants):
            await self.split_repo.add_participant(
                split_id=split_id,
                name=participant_data.name,
                color=participant_data.color,
                display_order=i,
                custom_amount=participant_data.custom_amount,
            )

        # Flush to ensure participants are written to DB before querying
        await self.db.flush()

        # Refresh to get new participants with eager loading
        split = await self.split_repo.get_by_id(split_id)

        # Create index-to-backend-UUID mapping
        sorted_participants = sorted(split.participants, key=lambda x: x.display_order)
        index_to_backend_id = {str(i): p.id for i, p in enumerate(sorted_participants)}

        # Add new assignments (always create new, never update existing after clear)
        for assignment_data in data.assignments:
            # Convert indices to backend participant UUIDs
            backend_participant_ids = []
            for participant_ref in assignment_data.participant_ids:
                if participant_ref in index_to_backend_id:
                    backend_participant_ids.append(index_to_backend_id[participant_ref])
                else:
                    backend_participant_ids.append(participant_ref)

            await self.split_repo.create_assignment(
                split_id=split_id,
                transaction_id=assignment_data.transaction_id,
                participant_ids=backend_participant_ids,
            )

        # Update recent friends
        await self.split_repo.update_recent_friends_from_split(
            user_id=user_id,
            participants=split.participants,
        )

        # Commit to persist all changes
        await self.db.commit()

        # Expire the cached object to ensure fresh relationship data is loaded
        # (required because expire_on_commit=False in session config)
        self.db.expire(split)
        split = await self.split_repo.get_by_id(split_id)
        return self._to_response(split)

    async def get_split(
        self,
        user_id: str,
        split_id: str,
    ) -> ExpenseSplitResponse:
        """Get an expense split by ID."""
        split = await self.split_repo.get_by_id_and_user(split_id, user_id)
        if not split:
            raise ResourceNotFoundError(f"Split {split_id} not found")
        return self._to_response(split)

    async def get_split_for_receipt(
        self,
        user_id: str,
        receipt_id: str,
    ) -> Optional[ExpenseSplitResponse]:
        """Get the expense split for a receipt, if one exists."""
        split = await self.split_repo.get_by_receipt(receipt_id, user_id)
        if not split:
            return None
        return self._to_response(split)

    async def delete_split(
        self,
        user_id: str,
        split_id: str,
    ) -> bool:
        """Delete an expense split."""
        split = await self.split_repo.get_by_id_and_user(split_id, user_id)
        if not split:
            raise ResourceNotFoundError(f"Split {split_id} not found")

        return await self.split_repo.delete(split_id)

    async def calculate_split(
        self,
        user_id: str,
        split_id: str,
    ) -> SplitCalculationResponse:
        """Calculate the split totals for each participant."""
        split = await self.split_repo.get_by_id_and_user(split_id, user_id)
        if not split:
            raise ResourceNotFoundError(f"Split {split_id} not found")

        # Get receipt for total
        receipt = await self.receipt_repo.get_by_id(split.receipt_id)
        if not receipt:
            raise ResourceNotFoundError(f"Receipt {split.receipt_id} not found")

        # Get all transactions for this receipt
        transactions = await self.transaction_repo.get_by_receipt(split.receipt_id)
        transaction_map = {t.id: t for t in transactions}

        # Build participant map
        participant_map = {p.id: p for p in split.participants}

        # Calculate totals per participant
        participant_totals: Dict[str, ParticipantTotal] = {}

        for participant in split.participants:
            participant_totals[participant.id] = ParticipantTotal(
                participant_id=participant.id,
                participant_name=participant.name,
                participant_color=participant.color,
                total_amount=0.0,
                item_count=0,
                items=[],
            )

        # Process each assignment
        for assignment in split.assignments:
            if not assignment.participant_ids:
                continue

            transaction = transaction_map.get(assignment.transaction_id)
            if not transaction:
                continue

            # Split amount evenly among participants
            num_participants = len(assignment.participant_ids)
            share_amount = round(transaction.item_price / num_participants, 2)

            for pid in assignment.participant_ids:
                if pid in participant_totals:
                    pt = participant_totals[pid]
                    pt.total_amount += share_amount
                    pt.item_count += 1
                    pt.items.append({
                        "item_name": transaction.item_name,
                        "item_price": transaction.item_price,
                        "share_amount": share_amount,
                    })

        # Round final totals
        for pt in participant_totals.values():
            pt.total_amount = round(pt.total_amount, 2)

        return SplitCalculationResponse(
            receipt_id=split.receipt_id,
            receipt_total=receipt.total_amount or 0.0,
            participant_totals=list(participant_totals.values()),
        )

    async def get_recent_friends(
        self,
        user_id: str,
        limit: int = 10,
    ) -> List[RecentFriendResponse]:
        """Get recent friends for quick-add."""
        friends = await self.split_repo.get_recent_friends(user_id, limit)
        return [
            RecentFriendResponse(
                id=f.id,
                name=f.name,
                color=f.color,
                last_used_at=f.last_used_at,
                use_count=f.use_count,
            )
            for f in friends
        ]

    async def generate_share_text(
        self,
        user_id: str,
        split_id: str,
    ) -> str:
        """Generate shareable text for a split."""
        calculation = await self.calculate_split(user_id, split_id)
        split = await self.split_repo.get_by_id_and_user(split_id, user_id)
        receipt = await self.receipt_repo.get_by_id(split.receipt_id)

        lines = []
        lines.append(f"Split for {receipt.store_name or 'Receipt'}")
        lines.append(f"Total: {calculation.receipt_total:.2f} EUR")
        lines.append("")

        for pt in calculation.participant_totals:
            lines.append(f"{pt.participant_name}: {pt.total_amount:.2f} EUR")

        lines.append("")
        lines.append("Sent from Scandalicious")

        return "\n".join(lines)

    def get_next_color(self, existing_count: int) -> str:
        """Get the next color from the palette."""
        return FRIEND_COLORS[existing_count % len(FRIEND_COLORS)]

    def _to_response(self, split: ExpenseSplit) -> ExpenseSplitResponse:
        """Convert model to response schema."""
        logger.info(
            f"_to_response: split_id={split.id}, "
            f"participants={len(split.participants)}, "
            f"assignments={len(split.assignments)}"
        )
        for a in split.assignments:
            logger.info(f"  Assignment: tx={a.transaction_id}, participants={a.participant_ids}")
        return ExpenseSplitResponse(
            id=split.id,
            receipt_id=split.receipt_id,
            participants=[
                SplitParticipantResponse(
                    id=p.id,
                    name=p.name,
                    color=p.color,
                    display_order=p.display_order,
                    custom_amount=p.custom_amount,
                    created_at=p.created_at,
                )
                for p in sorted(split.participants, key=lambda x: x.display_order)
            ],
            assignments=[
                SplitAssignmentResponse(
                    id=a.id,
                    transaction_id=a.transaction_id,
                    participant_ids=a.participant_ids,
                    created_at=a.created_at,
                    updated_at=a.updated_at,
                )
                for a in split.assignments
            ],
            created_at=split.created_at,
            updated_at=split.updated_at,
        )

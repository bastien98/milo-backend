from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.schemas.expense_split import (
    ExpenseSplitCreate,
    ExpenseSplitResponse,
    SplitCalculationResponse,
    RecentFriendResponse,
    ShareTextResponse,
    FRIEND_COLORS,
)
from app.services.expense_split_service import ExpenseSplitService

router = APIRouter()


@router.post("", response_model=ExpenseSplitResponse)
async def create_expense_split(
    data: ExpenseSplitCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Create a new expense split for a receipt.

    If a split already exists for this receipt, it will be updated instead.
    """
    service = ExpenseSplitService(db)
    result = await service.create_split(
        user_id=current_user.id,
        data=data,
    )
    # Commit handled in service for proper relationship refresh
    return result


@router.get("/recent-friends", response_model=list[RecentFriendResponse])
async def get_recent_friends(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Get recent friends for quick-add.

    Returns friends sorted by most recently used.
    """
    service = ExpenseSplitService(db)
    return await service.get_recent_friends(
        user_id=current_user.id,
        limit=limit,
    )


@router.get("/colors")
async def get_friend_colors():
    """
    Get the friend color palette.

    Returns the 8 vibrant colors used for friend avatars.
    """
    return {"colors": FRIEND_COLORS}


@router.get("/receipt/{receipt_id}", response_model=Optional[ExpenseSplitResponse])
async def get_split_for_receipt(
    receipt_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Get the expense split for a receipt, if one exists.

    Returns null if no split has been created for this receipt.
    """
    service = ExpenseSplitService(db)
    return await service.get_split_for_receipt(
        user_id=current_user.id,
        receipt_id=receipt_id,
    )


@router.get("/{split_id}", response_model=ExpenseSplitResponse)
async def get_expense_split(
    split_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Get an expense split by ID."""
    service = ExpenseSplitService(db)
    return await service.get_split(
        user_id=current_user.id,
        split_id=split_id,
    )


@router.put("/{split_id}", response_model=ExpenseSplitResponse)
async def update_expense_split(
    split_id: str,
    data: ExpenseSplitCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Update an expense split."""
    service = ExpenseSplitService(db)
    result = await service.update_split(
        user_id=current_user.id,
        split_id=split_id,
        data=data,
    )
    # Commit handled in service for proper relationship refresh
    return result


@router.delete("/{split_id}")
async def delete_expense_split(
    split_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Delete an expense split."""
    service = ExpenseSplitService(db)
    await service.delete_split(
        user_id=current_user.id,
        split_id=split_id,
    )
    await db.commit()
    return {"message": "Split deleted successfully"}


@router.get("/{split_id}/calculate", response_model=SplitCalculationResponse)
async def calculate_split(
    split_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Calculate the split totals for each participant.

    Returns the amount each person owes based on the item assignments.
    """
    service = ExpenseSplitService(db)
    return await service.calculate_split(
        user_id=current_user.id,
        split_id=split_id,
    )


@router.get("/{split_id}/share", response_model=ShareTextResponse)
async def get_share_text(
    split_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Generate shareable text for a split.

    Returns a formatted text summary suitable for sharing via Messages.
    """
    service = ExpenseSplitService(db)
    text = await service.generate_share_text(
        user_id=current_user.id,
        split_id=split_id,
    )
    return ShareTextResponse(text=text)

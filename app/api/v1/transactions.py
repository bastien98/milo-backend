from datetime import date
from typing import Optional
from math import ceil

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.models.enums import Category
from app.schemas.transaction import (
    TransactionResponse,
    TransactionListResponse,
    TransactionUpdate,
)
from app.db.repositories.transaction_repo import TransactionRepository
from app.core.exceptions import ResourceNotFoundError

router = APIRouter()


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    start_date: Optional[date] = Query(None, description="Filter by start date"),
    end_date: Optional[date] = Query(None, description="Filter by end date"),
    store_name: Optional[str] = Query(None, description="Filter by store name"),
    category: Optional[Category] = Query(None, description="Filter by category"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    List transactions with optional filters.

    Supports filtering by date range, store name, and category.
    Results are paginated.
    """
    transaction_repo = TransactionRepository(db)

    transactions, total = await transaction_repo.get_by_user(
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
        store_name=store_name,
        category=category,
        page=page,
        page_size=page_size,
    )

    total_pages = ceil(total / page_size) if total > 0 else 1

    return TransactionListResponse(
        transactions=[TransactionResponse.model_validate(t) for t in transactions],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Get a specific transaction by ID."""
    transaction_repo = TransactionRepository(db)

    transaction = await transaction_repo.get_by_id_and_user(
        transaction_id=transaction_id,
        user_id=current_user.id,
    )

    if not transaction:
        raise ResourceNotFoundError(f"Transaction {transaction_id} not found")

    return TransactionResponse.model_validate(transaction)


@router.put("/{transaction_id}", response_model=TransactionResponse)
async def update_transaction(
    transaction_id: str,
    update_data: TransactionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """
    Update a transaction.

    Useful for correcting category misclassifications or fixing item details.
    """
    transaction_repo = TransactionRepository(db)

    # Verify ownership
    transaction = await transaction_repo.get_by_id_and_user(
        transaction_id=transaction_id,
        user_id=current_user.id,
    )

    if not transaction:
        raise ResourceNotFoundError(f"Transaction {transaction_id} not found")

    # Update with provided fields
    updated = await transaction_repo.update(
        transaction_id=transaction_id,
        store_name=update_data.store_name,
        item_name=update_data.item_name,
        item_price=update_data.item_price,
        quantity=update_data.quantity,
        unit_price=update_data.unit_price,
        category=update_data.category,
        date=update_data.date,
    )

    return TransactionResponse.model_validate(updated)


@router.delete("/{transaction_id}")
async def delete_transaction(
    transaction_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Delete a transaction."""
    transaction_repo = TransactionRepository(db)

    # Verify ownership
    transaction = await transaction_repo.get_by_id_and_user(
        transaction_id=transaction_id,
        user_id=current_user.id,
    )

    if not transaction:
        raise ResourceNotFoundError(f"Transaction {transaction_id} not found")

    await transaction_repo.delete(transaction_id)

    return {"message": "Transaction deleted successfully"}

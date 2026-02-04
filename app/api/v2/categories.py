from fastapi import APIRouter, Depends, Query
from typing import Optional
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date
import calendar

from app.api.deps import get_db, get_current_db_user
from app.models.user import User
from app.models.transaction import Transaction
from app.services.category_registry import get_category_registry

router = APIRouter()


@router.get("")
async def get_category_hierarchy(
    current_user: User = Depends(get_current_db_user),
):
    """Get the full category hierarchy (groups, categories, sub-categories)."""
    registry = get_category_registry()
    return registry.get_hierarchy()


@router.get("/used")
async def get_used_categories(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2020, le=2100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
):
    """Get categories that the user has actual spending data for.

    If month/year provided, returns categories used in that month.
    If not provided, returns all categories the user has ever used.
    """
    registry = get_category_registry()

    # Build query
    conditions = [Transaction.user_id == current_user.id]

    if month and year:
        first_day = date(year, month, 1)
        last_day = date(year, month, calendar.monthrange(year, month)[1])
        conditions.append(Transaction.date >= first_day)
        conditions.append(Transaction.date <= last_day)

    # Get distinct categories with spending
    result = await db.execute(
        select(
            Transaction.category,
            func.sum(Transaction.item_price).label("total_spent"),
            func.count(Transaction.id).label("transaction_count"),
        )
        .where(and_(*conditions))
        .group_by(Transaction.category)
        .order_by(func.sum(Transaction.item_price).desc())
    )
    rows = result.all()

    # Build response with hierarchy info
    used_categories = []
    for row in rows:
        sub_category = row.category
        info = registry.get_info(sub_category)
        used_categories.append({
            "sub_category": sub_category,
            "category": info.category if info else "Uncategorized",
            "group": info.group if info else "Miscellaneous",
            "total_spent": float(row.total_spent),
            "transaction_count": row.transaction_count,
            "color_hex": registry.get_group_color(sub_category),
            "icon": registry.get_group_icon(sub_category),
            "category_id": registry.get_category_id(sub_category),
        })

    return {"categories": used_categories}

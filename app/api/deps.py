from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_maker
from app.core.security import get_current_user, FirebaseUser
from app.db.repositories.user_repo import UserRepository
from app.models.user import User


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Database session dependency."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_current_db_user(
    firebase_user: FirebaseUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Get or create database user from Firebase auth.

    This ensures the user exists in our database and returns
    the SQLAlchemy User model for use in endpoints.
    """
    user_repo = UserRepository(db)

    # Try to find existing user
    user = await user_repo.get_by_firebase_uid(firebase_user.uid)

    if user is None:
        # Create new user on first authentication
        user = await user_repo.create(
            firebase_uid=firebase_user.uid,
            email=firebase_user.email,
            display_name=firebase_user.name,
        )

    return user

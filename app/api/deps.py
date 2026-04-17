import asyncio
from typing import AsyncGenerator, Optional

import firebase_admin
from fastapi import Depends, Request
from firebase_admin import auth
from sqlalchemy.exc import IntegrityError
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
        # Create new user on first authentication.
        # Handle race condition: concurrent requests for a new user can both
        # see user=None and try to INSERT, causing a unique constraint violation.
        try:
            user = await user_repo.create(
                firebase_uid=firebase_user.uid,
                email=firebase_user.email,
                display_name=firebase_user.name,
            )
        except IntegrityError:
            await db.rollback()
            user = await user_repo.get_by_firebase_uid(firebase_user.uid)

    return user


async def get_optional_db_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Return the authenticated User if a valid bearer token is present,
    otherwise None. Never raises 401 — use on endpoints that must serve
    both authenticated and anonymous callers (e.g. public browsing that
    optionally personalizes if signed in).
    """
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None

    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return None

    try:
        decoded = await asyncio.to_thread(auth.verify_id_token, token)
    except (
        auth.ExpiredIdTokenError,
        auth.InvalidIdTokenError,
        firebase_admin.exceptions.FirebaseError,
        Exception,
    ):
        return None

    firebase_uid = decoded.get("uid")
    if not firebase_uid:
        return None

    user_repo = UserRepository(db)
    user = await user_repo.get_by_firebase_uid(firebase_uid)
    if user is None:
        try:
            user = await user_repo.create(
                firebase_uid=firebase_uid,
                email=decoded.get("email"),
                display_name=decoded.get("name"),
            )
        except IntegrityError:
            await db.rollback()
            user = await user_repo.get_by_firebase_uid(firebase_uid)

    return user

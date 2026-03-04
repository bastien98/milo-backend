"""Startup script that handles both fresh and existing databases.

For fresh databases: creates tables from SQLAlchemy models, then stamps alembic.
For existing databases: runs normal alembic upgrade head.
"""
import asyncio
import subprocess
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

settings = get_settings()


async def is_fresh_database() -> bool:
    """Check if the database has no user tables (fresh/empty)."""
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'public'"
        ))
        count = result.scalar()
    await engine.dispose()
    return count == 0


async def create_tables_from_models():
    """Create all tables from SQLAlchemy models."""
    from app.db.base import Base
    # Import all models to register them
    from app.models import (  # noqa
        user, receipt, transaction, user_rate_limit,
        user_profile, budget, budget_history, user_enriched_profile,
    )

    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("Created all tables from models")


def stamp_alembic_head():
    """Stamp alembic to the latest head without running migrations."""
    result = subprocess.run(
        ["alembic", "stamp", "head"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"alembic stamp failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    print("Stamped alembic to head")


def run_alembic_upgrade():
    """Run normal alembic upgrade head."""
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"alembic upgrade failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    print("Alembic upgrade complete")


async def main():
    if await is_fresh_database():
        print("Fresh database detected - creating tables from models")
        await create_tables_from_models()
        stamp_alembic_head()
    else:
        print("Existing database detected - running alembic upgrade")
        run_alembic_upgrade()


if __name__ == "__main__":
    asyncio.run(main())

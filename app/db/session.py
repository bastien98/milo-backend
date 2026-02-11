from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.base import Base

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,  # Detect stale connections before using them
    echo=False,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db():
    """Initialize database tables.

    When USE_ALEMBIC=True (default, production):
        - Skips create_all() since Alembic handles migrations
        - The railway.json startCommand runs 'alembic upgrade head' before starting the app

    When USE_ALEMBIC=False (development):
        - Uses create_all() for convenience (creates tables if they don't exist)
    """
    # Import all models to ensure they're registered with SQLAlchemy
    from app.models import user, receipt, transaction, user_rate_limit, user_profile, budget, budget_history  # noqa
    from app.models import user_enriched_profile  # noqa

    if not settings.USE_ALEMBIC:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


async def get_async_session():
    """Get async database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

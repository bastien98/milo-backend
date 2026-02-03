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
    import logging
    logger = logging.getLogger(__name__)

    # Import all models to ensure they're registered with SQLAlchemy
    from app.models import user, receipt, transaction, user_rate_limit, user_profile, budget, budget_ai_insight, budget_history  # noqa
    from app.models import bank_connection, bank_account, bank_transaction  # noqa
    from app.models import user_enriched_profile  # noqa

    if settings.USE_ALEMBIC:
        logger.info("Database models registered. Using Alembic for migrations (USE_ALEMBIC=True).")
    else:
        logger.info("Running create_all() for database initialization (USE_ALEMBIC=False).")
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

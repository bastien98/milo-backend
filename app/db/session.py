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
    """Initialize database tables using SQLAlchemy create_all().

    Skipped by default (SKIP_DB_INIT=True) since database is already set up.
    Set SKIP_DB_INIT=False for fresh databases.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Import all models to ensure they're registered with SQLAlchemy
    from app.models import user, receipt, transaction, user_rate_limit, user_profile, budget, budget_ai_insight  # noqa
    from app.models import bank_connection, bank_account, bank_transaction  # noqa

    if settings.SKIP_DB_INIT:
        logger.info("Skipping database initialization (SKIP_DB_INIT=True).")
        return

    logger.info("Running create_all() for database initialization.")
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, checkfirst=True))
    logger.info("Database initialization complete.")


async def get_async_session():
    """Get async database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

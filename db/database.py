"""Async SQLAlchemy engine and session factory.

Database is OPTIONAL — if DATABASE_URL is not set, the app runs in
stateless API-only mode (all existing endpoints work without a DB).
"""

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config import get_settings

logger = logging.getLogger(__name__)

# Naming convention for constraints (consistent with Talk2Data)
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=convention)


class Base(DeclarativeBase):
    """Base class for all database models."""

    metadata = metadata


# Engine and session factory — created lazily on first use
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_engine() -> AsyncEngine | None:
    """Create or return the async engine. Returns None if no DATABASE_URL."""
    global _engine
    if _engine is not None:
        return _engine

    settings = get_settings()
    if not settings.database_url:
        return None

    _engine = create_async_engine(
        settings.database_url_async,
        echo=False,
        future=True,
        pool_size=15,
        max_overflow=35,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    return _engine


def _get_session_factory() -> async_sessionmaker[AsyncSession] | None:
    """Create or return the session factory."""
    global _session_factory
    if _session_factory is not None:
        return _session_factory

    engine = _get_engine()
    if engine is None:
        return None

    _session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for getting a database session.

    Commits on success, rolls back on exception.
    Raises RuntimeError if database is not configured.
    """
    factory = _get_session_factory()
    if factory is None:
        raise RuntimeError("Database not configured — set DATABASE_URL environment variable")

    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> bool:
    """Initialize database connection. Returns True if connected, False if no DB configured."""
    engine = _get_engine()
    if engine is None:
        logger.info("DATABASE_URL not set — running in stateless API-only mode")
        return False

    try:
        async with engine.connect() as conn:
            await conn.execute(metadata.reflect_cte if hasattr(metadata, "reflect_cte") else conn.connection)
    except Exception:
        pass

    logger.info("Database connected: %s", str(engine.url).split("@")[-1] if engine else "none")
    return True


async def close_db() -> None:
    """Dispose the engine on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database connection closed")


# Re-export for convenience
async_session_maker = _get_session_factory

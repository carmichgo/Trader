"""Async database session management using asyncpg + SQLAlchemy 2.0."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from packages.core.db.models import Base

_DATABASE_URL_DEFAULT = "postgresql+asyncpg://trader:trader@localhost:5432/trader"

async_engine: AsyncEngine = create_async_engine(
    os.environ.get("DATABASE_URL", _DATABASE_URL_DEFAULT),
    echo=os.environ.get("SQL_ECHO", "false").lower() == "true",
    pool_size=int(os.environ.get("DB_POOL_SIZE", "10")),
    max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "20")),
    pool_pre_ping=True,
    pool_recycle=300,
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


def reconfigure_engine(url: str | None = None, **kwargs: object) -> None:
    """Recreate the engine and session factory with a new URL or options.

    Call this early at startup if the URL comes from a config object rather
    than an environment variable.
    """
    global async_engine, AsyncSessionLocal

    async_engine = create_async_engine(
        url or os.environ.get("DATABASE_URL", _DATABASE_URL_DEFAULT),
        echo=kwargs.pop("echo", False),  # type: ignore[arg-type]
        pool_size=kwargs.pop("pool_size", 10),  # type: ignore[arg-type]
        max_overflow=kwargs.pop("max_overflow", 20),  # type: ignore[arg-type]
        pool_pre_ping=True,
        pool_recycle=300,
        **kwargs,
    )
    AsyncSessionLocal = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def init_db() -> None:
    """Create all tables defined in the ORM metadata.

    For production use Alembic migrations instead; this is a convenience
    helper for development and testing.
    """
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_db() -> None:
    """Drop all tables. **Destructive** -- use only in tests."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session, suitable as a FastAPI dependency.

    Usage::

        @app.get("/items")
        async def items(session: AsyncSession = Depends(get_session)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def dispose_engine() -> None:
    """Dispose of the connection pool. Call on application shutdown."""
    await async_engine.dispose()

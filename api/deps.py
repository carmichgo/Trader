"""Dependency injection helpers for FastAPI routes."""

from __future__ import annotations

import functools
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.config import SystemConfig
from packages.core.db.postgres import AsyncSessionLocal

# ---------------------------------------------------------------------------
# Config singleton
# ---------------------------------------------------------------------------

_config: SystemConfig | None = None


def get_config() -> SystemConfig:
    """Return the global SystemConfig singleton (loaded once)."""
    global _config
    if _config is None:
        _config = SystemConfig()
    return _config


# ---------------------------------------------------------------------------
# Database session dependency
# ---------------------------------------------------------------------------


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session; commits on success, rolls back on error."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Redis dependency
# ---------------------------------------------------------------------------

_redis: Any = None


async def init_redis(url: str) -> None:
    """Create the global async Redis client. Called during app lifespan startup."""
    global _redis
    import redis.asyncio as aioredis

    _redis = aioredis.from_url(url, decode_responses=True)
    # Verify connectivity
    await _redis.ping()


async def close_redis() -> None:
    """Close the global Redis connection. Called during app lifespan shutdown."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def get_redis() -> Any:
    """FastAPI dependency that returns the shared async Redis client."""
    if _redis is None:
        raise RuntimeError("Redis is not connected. Check application startup.")
    return _redis

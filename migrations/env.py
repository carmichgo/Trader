"""Alembic environment configuration with async SQLAlchemy support.

Imports all ORM models so Alembic's autogenerate can detect schema changes.
Uses the database URL from SystemConfig (config.yaml + .env).
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so `packages.*` imports work.
# ---------------------------------------------------------------------------
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Import ALL ORM models so Base.metadata includes every table.
# ---------------------------------------------------------------------------
from packages.core.db.models import (  # noqa: E402, F401
    Base,
    Goal,
    StrategistPlan,
    Trade,
    PortfolioSnapshot,
    AIDecision,
    MarketData,
    DailyPerformance,
)
from packages.core.config import SystemConfig  # noqa: E402

# Alembic Config object -- provides access to alembic.ini values.
config = context.config

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# MetaData for autogenerate support
target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# Resolve the database URL from our application config.
# ---------------------------------------------------------------------------

def _get_database_url() -> str:
    """Build the async database URL from SystemConfig."""
    cfg = SystemConfig()
    return cfg.database.url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    """
    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations using the provided connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with an async engine."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (async wrapper)."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Entry point: choose offline or online mode.
# ---------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

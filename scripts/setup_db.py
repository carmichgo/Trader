#!/usr/bin/env python3
"""Initialize the database: create tables, set up TimescaleDB hypertables.

Usage:
    python scripts/setup_db.py [--drop]

Flags:
    --drop    Drop all tables before recreating (DESTRUCTIVE).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from packages.core.config import SystemConfig
from packages.core.db.postgres import (
    reconfigure_engine,
    init_db,
    drop_db,
    dispose_engine,
    async_engine,
    AsyncSessionLocal,
)
from packages.core.db.timescale import setup_hypertables
from packages.core.db.models import Base  # noqa: F401 -- ensure models are loaded

import structlog

logger = structlog.get_logger(__name__)


async def main(drop: bool = False) -> None:
    """Run the full database setup sequence."""
    config = SystemConfig()

    logger.info("setup_db_start", db_url=config.database.url, drop=drop)

    # Reconfigure the global engine with resolved config
    reconfigure_engine(
        url=config.database.url,
        echo=config.database.echo,
        pool_size=config.database.pool_size,
        max_overflow=config.database.max_overflow,
    )

    try:
        # Optionally drop all tables
        if drop:
            logger.warning("dropping_all_tables")
            await drop_db()
            logger.info("tables_dropped")

        # Create all tables from ORM metadata
        logger.info("creating_tables")
        await init_db()
        logger.info("tables_created")

        # Set up TimescaleDB hypertables for time-series tables
        logger.info("setting_up_hypertables")
        try:
            await setup_hypertables()
            logger.info("hypertables_configured")
        except Exception as exc:
            logger.warning(
                "hypertable_setup_failed",
                error=str(exc),
                hint="TimescaleDB extension may not be installed. "
                     "Tables will still work as regular PostgreSQL tables.",
            )

        # Create continuous aggregates for common queries (optional)
        async with AsyncSessionLocal() as session:
            try:
                from sqlalchemy import text

                # Hourly portfolio summary (materialized view)
                await session.execute(text("""
                    CREATE MATERIALIZED VIEW IF NOT EXISTS portfolio_hourly
                    WITH (timescaledb.continuous) AS
                    SELECT
                        time_bucket('1 hour', time) AS bucket,
                        last(total_capital, time) AS total_capital,
                        last(polymarket_capital, time) AS polymarket_capital,
                        last(crypto_capital, time) AS crypto_capital,
                        last(stocks_capital, time) AS stocks_capital,
                        last(drawdown_from_peak, time) AS drawdown_from_peak,
                        max(total_capital) AS peak_capital,
                        min(total_capital) AS trough_capital
                    FROM portfolio_snapshots
                    GROUP BY bucket
                    WITH NO DATA
                """))
                await session.commit()
                logger.info("continuous_aggregates_created")
            except Exception as exc:
                await session.rollback()
                logger.warning(
                    "continuous_aggregates_skipped",
                    error=str(exc),
                    hint="Requires TimescaleDB hypertables to be set up first.",
                )

        logger.info("setup_db_complete")

    finally:
        await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialize the trading system database.")
    parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop all tables before recreating (DESTRUCTIVE)",
    )
    args = parser.parse_args()

    asyncio.run(main(drop=args.drop))

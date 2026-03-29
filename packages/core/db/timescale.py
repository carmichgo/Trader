"""TimescaleDB helper functions for hypertable management and time-series queries."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.db.models import MarketData, PortfolioSnapshot
from packages.core.db.postgres import AsyncSessionLocal


async def setup_hypertables(session: AsyncSession | None = None) -> None:
    """Convert time-series tables into TimescaleDB hypertables.

    Safe to call multiple times -- uses ``if_not_exists``.  Should be
    called once after :func:`packages.core.db.postgres.init_db`.
    """
    owns_session = session is None
    if owns_session:
        session = AsyncSessionLocal()

    try:
        await session.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))

        await session.execute(
            text(
                "SELECT create_hypertable("
                "'market_data', 'time', if_not_exists => TRUE, "
                "migrate_data => TRUE"
                ")"
            )
        )

        await session.execute(
            text(
                "SELECT create_hypertable("
                "'portfolio_snapshots', 'time', if_not_exists => TRUE, "
                "migrate_data => TRUE"
                ")"
            )
        )

        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        if owns_session:
            await session.close()


async def insert_market_data(
    session: AsyncSession,
    *,
    time: datetime,
    market: str,
    asset: str,
    open: Decimal | float,
    high: Decimal | float,
    low: Decimal | float,
    close: Decimal | float,
    volume: Decimal | float | None = None,
    extra: dict[str, Any] | None = None,
) -> MarketData:
    """Insert a single OHLCV row into the market_data hypertable.

    Uses an upsert (ON CONFLICT DO UPDATE) so re-ingesting the same
    candle is idempotent.
    """
    stmt = text(
        """
        INSERT INTO market_data (time, market, asset, open, high, low, close, volume, extra)
        VALUES (:time, :market, :asset, :open, :high, :low, :close, :volume, :extra::jsonb)
        ON CONFLICT (time, market, asset)
        DO UPDATE SET
            open    = EXCLUDED.open,
            high    = EXCLUDED.high,
            low     = EXCLUDED.low,
            close   = EXCLUDED.close,
            volume  = EXCLUDED.volume,
            extra   = EXCLUDED.extra
        RETURNING *
        """
    )
    import json

    result = await session.execute(
        stmt,
        {
            "time": time,
            "market": market,
            "asset": asset,
            "open": float(open),
            "high": float(high),
            "low": float(low),
            "close": float(close),
            "volume": float(volume) if volume is not None else None,
            "extra": json.dumps(extra) if extra is not None else None,
        },
    )
    row = result.mappings().one()
    await session.commit()

    return MarketData(
        time=row["time"],
        market=row["market"],
        asset=row["asset"],
        open=row["open"],
        high=row["high"],
        low=row["low"],
        close=row["close"],
        volume=row["volume"],
        extra=row["extra"],
    )


async def query_ohlcv(
    session: AsyncSession,
    *,
    market: str,
    asset: str,
    start: datetime,
    end: datetime,
    bucket_interval: str = "1 hour",
    limit: int = 1000,
) -> Sequence[dict[str, Any]]:
    """Query OHLCV data, optionally bucketed via TimescaleDB ``time_bucket``.

    Parameters
    ----------
    session:
        Active async database session.
    market:
        Market identifier (e.g. ``"crypto"``, ``"polymarket"``).
    asset:
        Asset symbol (e.g. ``"BTC/USDT"``).
    start / end:
        Time range (inclusive).
    bucket_interval:
        PostgreSQL interval string for ``time_bucket`` aggregation.
        Pass ``"raw"`` to skip aggregation and return individual rows.
    limit:
        Maximum number of rows to return.
    """
    if bucket_interval == "raw":
        stmt = text(
            """
            SELECT time, market, asset, open, high, low, close, volume, extra
            FROM market_data
            WHERE market = :market AND asset = :asset
              AND time >= :start AND time <= :end
            ORDER BY time ASC
            LIMIT :limit
            """
        )
    else:
        stmt = text(
            """
            SELECT
                time_bucket(:bucket, time) AS time,
                :market AS market,
                :asset  AS asset,
                first(open, time)  AS open,
                max(high)          AS high,
                min(low)           AS low,
                last(close, time)  AS close,
                sum(volume)        AS volume
            FROM market_data
            WHERE market = :market AND asset = :asset
              AND time >= :start AND time <= :end
            GROUP BY 1
            ORDER BY 1 ASC
            LIMIT :limit
            """
        )

    params: dict[str, Any] = {
        "market": market,
        "asset": asset,
        "start": start,
        "end": end,
        "limit": limit,
    }
    if bucket_interval != "raw":
        params["bucket"] = bucket_interval

    result = await session.execute(stmt, params)
    return [dict(row._mapping) for row in result.fetchall()]


async def insert_portfolio_snapshot(
    session: AsyncSession,
    *,
    time: datetime,
    total_capital: Decimal | float,
    polymarket_capital: Decimal | float | None = None,
    crypto_capital: Decimal | float | None = None,
    stocks_capital: Decimal | float | None = None,
    total_unrealized_pnl: Decimal | float | None = None,
    total_realized_pnl_today: Decimal | float | None = None,
    open_positions_count: int | None = None,
    daily_inference_cost: Decimal | float | None = None,
    daily_trading_fees: Decimal | float | None = None,
    drawdown_from_peak: Decimal | float | None = None,
) -> PortfolioSnapshot:
    """Insert a portfolio snapshot row (upsert on time PK)."""
    stmt = text(
        """
        INSERT INTO portfolio_snapshots (
            time, total_capital, polymarket_capital, crypto_capital,
            stocks_capital, total_unrealized_pnl, total_realized_pnl_today,
            open_positions_count, daily_inference_cost, daily_trading_fees,
            drawdown_from_peak
        ) VALUES (
            :time, :total_capital, :polymarket_capital, :crypto_capital,
            :stocks_capital, :total_unrealized_pnl, :total_realized_pnl_today,
            :open_positions_count, :daily_inference_cost, :daily_trading_fees,
            :drawdown_from_peak
        )
        ON CONFLICT (time)
        DO UPDATE SET
            total_capital           = EXCLUDED.total_capital,
            polymarket_capital      = EXCLUDED.polymarket_capital,
            crypto_capital          = EXCLUDED.crypto_capital,
            stocks_capital          = EXCLUDED.stocks_capital,
            total_unrealized_pnl    = EXCLUDED.total_unrealized_pnl,
            total_realized_pnl_today= EXCLUDED.total_realized_pnl_today,
            open_positions_count    = EXCLUDED.open_positions_count,
            daily_inference_cost    = EXCLUDED.daily_inference_cost,
            daily_trading_fees      = EXCLUDED.daily_trading_fees,
            drawdown_from_peak      = EXCLUDED.drawdown_from_peak
        RETURNING *
        """
    )

    def _f(v: Decimal | float | None) -> float | None:
        return float(v) if v is not None else None

    result = await session.execute(
        stmt,
        {
            "time": time,
            "total_capital": float(total_capital),
            "polymarket_capital": _f(polymarket_capital),
            "crypto_capital": _f(crypto_capital),
            "stocks_capital": _f(stocks_capital),
            "total_unrealized_pnl": _f(total_unrealized_pnl),
            "total_realized_pnl_today": _f(total_realized_pnl_today),
            "open_positions_count": open_positions_count,
            "daily_inference_cost": _f(daily_inference_cost),
            "daily_trading_fees": _f(daily_trading_fees),
            "drawdown_from_peak": _f(drawdown_from_peak),
        },
    )
    row = result.mappings().one()
    await session.commit()

    return PortfolioSnapshot(**row)
